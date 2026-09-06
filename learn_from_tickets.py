"""Read past support conversations and distil how the team actually answers.

Reads the history of every text channel in the configured categories, works out
how Billi, Euan and Professor handle people, and writes the result to
knowledge/team-style.md so Salena answers the way they do.

Strictly read-only. It issues GET requests and writes one local file. It never
posts, edits, deletes or reacts to anything on Discord.

  python learn_from_tickets.py --scan      # what is there, no model calls
  python learn_from_tickets.py             # scan, summarise, write the file

These are real support tickets, so the summary captures PATTERNS, never
people: no customer names, wallet addresses, amounts, transaction ids or
anything else that identifies a specific person or trade. The prompt says so
and the output is scrubbed afterwards, because this text ends up in a prompt
that answers strangers in public.
"""

import argparse
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from llm import ask_llm  # noqa: E402  (needs .env loaded first)

API = "https://discord.com/api/v9"
TOKEN = os.getenv("DISCORD_USER_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "925207817923743794").strip()

# "stuff" and "misc" by default; override with LEARN_CATEGORY_IDS.
CATEGORY_IDS = [
    c.strip() for c in
    (os.getenv("LEARN_CATEGORY_IDS", "") or "1305503692929110106,1509163128636702842").split(",")
    if c.strip()
]

# Whose replies we are learning from. Matched case-insensitively as substrings,
# so "professordecoder" matches "professor".
TEAM = [t.strip().lower() for t in
        (os.getenv("LEARN_TEAM", "") or "billi,euan,professor").split(",") if t.strip()]

MESSAGES_PER_CHANNEL = int(os.getenv("LEARN_MESSAGES_PER_CHANNEL", "300"))
OUT = Path(__file__).with_name("knowledge") / "team-style.md"

HEADERS = {"Authorization": TOKEN}


def _get(path, **params):
    for attempt in range(4):
        r = requests.get(API + path, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 429:
            wait = min(float(r.json().get("retry_after", 1)), 30)
            time.sleep(wait)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 404):
            return None          # not visible to us, skip quietly
        r.raise_for_status()
    return None


def channels_in_categories():
    everything = _get("/guilds/{}/channels".format(GUILD_ID)) or []
    wanted = set(CATEGORY_IDS)
    names = {str(c["id"]): c.get("name") or str(c["id"]) for c in everything}
    picked = [
        (str(c["id"]), c.get("name") or str(c["id"]))
        for c in everything
        if c.get("type") in (0, 5) and str(c.get("parent_id") or "") in wanted
    ]
    return sorted(picked, key=lambda p: p[1]), names


def history(channel_id, limit):
    """Oldest-first messages, paged backwards from the most recent."""
    out, before = [], None
    while len(out) < limit:
        batch = _get("/channels/{}/messages".format(channel_id),
                     limit=min(100, limit - len(out)),
                     **({"before": before} if before else {}))
        if not batch:
            break
        out.extend(batch)
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
        time.sleep(0.4)
    return list(reversed(out))


def is_team(name):
    low = (name or "").lower()
    return any(t in low for t in TEAM)


def transcript(messages):
    """Readable transcript, trimmed to what is useful for learning tone."""
    lines = []
    for m in messages:
        author = m.get("author") or {}
        name = author.get("global_name") or author.get("username") or "?"
        if author.get("bot"):
            continue
        text = (m.get("content") or "").strip()
        if not text:
            continue
        tag = "TEAM" if is_team(name) else "user"
        lines.append("[{}] {}: {}".format(tag, name, text[:600]))
    return "\n".join(lines)


# Anything that slips past the prompt gets removed here.
_SCRUB = [
    (re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"), "[wallet]"),      # base58 / solana
    (re.compile(r"\b0x[a-fA-F0-9]{40}\b"), "[wallet]"),                # evm
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (re.compile(r"\b\d{17,20}\b"), "[id]"),                            # snowflakes
]


def scrub(text):
    for pattern, repl in _SCRUB:
        text = pattern.sub(repl, text)
    return text


CHANNEL_PROMPT = """Below is a support conversation from a crypto trading
Discord. Lines marked [TEAM] are staff; [user] lines are customers.

Summarise, in plain prose, ONLY what would help someone new answer like the
team does:

- recurring problems here and how staff resolved them
- how staff talk: length, tone, formality, what they do and do not explain
- what they refuse to do, and what they escalate or hand to someone else
- anything factual about the products that a support person should know

Hard rules. This summary goes into a prompt that answers strangers in public:
- Never name or describe a customer, and never quote them identifiably
- No wallet addresses, transaction ids, amounts, balances or dates
- No details of any individual case. Patterns across cases only
- If the channel has nothing useful in it, reply with exactly: NOTHING USEFUL

Conversation:
{body}
"""

FINAL_PROMPT = """You have per-channel notes from a crypto Discord's support
history. Merge them into one briefing that teaches a new support person how
this team works.

Structure it as:
## How the team answers      (tone, length, habits, worth imitating)
## Problems that come up a lot   (and the resolution each time)
## What staff never do
## What gets handed to a human

Keep it under 700 words, concrete, and free of any individual's details.
Drop anything that appears only once, unless it is a rule about what not to do.

Notes:
{body}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true",
                    help="report what is there without calling the model")
    ap.add_argument("--limit", type=int, default=MESSAGES_PER_CHANNEL)
    args = ap.parse_args()

    if not TOKEN:
        sys.exit("DISCORD_USER_TOKEN is not set in .env")

    channels, _ = channels_in_categories()
    if not channels:
        sys.exit("No readable channels found in categories: {}".format(", ".join(CATEGORY_IDS)))

    print("{} channel(s) across {} categor(ies)\n".format(len(channels), len(CATEGORY_IDS)))

    corpus, totals, authors = [], Counter(), Counter()
    for cid, cname in channels:
        msgs = history(cid, args.limit)
        text = transcript(msgs)
        team_lines = text.count("[TEAM]")
        totals[cname] = len(msgs)
        for m in msgs:
            a = (m.get("author") or {})
            if not a.get("bot"):
                authors[a.get("global_name") or a.get("username") or "?"] += 1
        print("  {:44} {:4} msgs, {:3} from team".format("#" + cname[:42], len(msgs), team_lines))
        if text and team_lines:
            corpus.append((cname, scrub(text)))
        time.sleep(0.3)

    print("\ntotal messages: {}".format(sum(totals.values())))
    print("top posters:")
    for who, n in authors.most_common(12):
        print("   {:28} {:5}  {}".format(who, n, "(team)" if is_team(who) else ""))
    print("\nchannels with team replies to learn from: {}".format(len(corpus)))

    if args.scan:
        print("\n--scan only, no model calls made, nothing written")
        return

    print("\nsummarising per channel...")
    notes = []
    for cname, text in corpus:
        try:
            note = ask_llm(CHANNEL_PROMPT.format(body=text[:14000]),
                           [{"role": "user", "content": "Summarise it."}])
        except Exception as exc:
            print("   {} failed: {}".format(cname, exc))
            continue
        if "NOTHING USEFUL" in note.upper():
            print("   #{}: nothing useful".format(cname))
            continue
        notes.append("### #{}\n{}".format(cname, note))
        print("   #{}: {} chars".format(cname, len(note)))

    if not notes:
        sys.exit("Nothing worth writing.")

    print("\nmerging into one briefing...")
    final = ask_llm(FINAL_PROMPT.format(body=scrub("\n\n".join(notes))[:40000]),
                    [{"role": "user", "content": "Write the briefing."}])

    OUT.write_text(
        "# How this team handles support\n\n"
        "Distilled from past ticket history by learn_from_tickets.py. Patterns "
        "only: no individual customers, cases, wallets or amounts.\n\n"
        + scrub(final).strip() + "\n",
        encoding="utf-8",
    )
    print("\nwrote {} ({} chars)".format(OUT, OUT.stat().st_size))
    print("It loads into every answer automatically. Read it before trusting it.")


if __name__ == "__main__":
    main()
