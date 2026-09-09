"""Build a local, searchable index of approved Discord support history.

This read-only command fetches messages from the channels/categories already
configured for the support bot, stores a local scrubbed index under .runtime,
and never posts to Discord. The bot retrieves a few relevant excerpts per
question instead of sending the whole history to OpenAI.

Run: python index_discord_history.py --scan
     python index_discord_history.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

API = "https://discord.com/api/v9"
TOKEN = os.getenv("DISCORD_USER_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "925207817923743794").strip()
OUTPUT_CHANNEL_ID = "1546057978921095178"
INDEX_PATH = ROOT / ".runtime" / "discord_history_index.json"
TEAM_IDS = {
    value.strip()
    for value in os.getenv(
        "HISTORY_STAFF_IDS",
        "1161631744768884746,1477996916435320833,922701376759410758",
    ).split(",")
    if value.strip()
}
HEADERS = {"Authorization": TOKEN}

# Preserve searchable wording without persisting wallet addresses, hashes,
# emails, or Discord snowflakes in the local index.
_SCRUB = [
    (re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,64}\b"), "[wallet-or-hash]"),
    (re.compile(r"\b0x[a-fA-F0-9]{40,64}\b"), "[wallet-or-hash]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (re.compile(r"\b\d{17,20}\b"), "[discord-id]"),
]


def scrub(text: str) -> str:
    for pattern, replacement in _SCRUB:
        text = pattern.sub(replacement, text)
    return text


def _get(path: str, **params):
    for _ in range(5):
        response = requests.get(API + path, headers=HEADERS, params=params, timeout=30)
        if response.status_code == 429:
            try:
                wait = min(float(response.json().get("retry_after", 1)), 30)
            except (ValueError, TypeError):
                wait = 2
            time.sleep(wait)
            continue
        if response.status_code in (403, 404):
            return None
        if response.status_code == 200:
            return response.json()
        response.raise_for_status()
    return None


def _ids(name: str) -> set[str]:
    return {
        item.strip()
        for item in os.getenv(name, "").replace(" ", "").split(",")
        if item.strip().isdigit()
    }


def channels_to_index() -> list[dict]:
    channels = _get(f"/guilds/{GUILD_ID}/channels") or []
    explicit = _ids("WATCH_CHANNEL_IDS") | _ids("ALLOWED_CHANNEL_IDS")
    categories = _ids("WATCH_CATEGORY_IDS") | _ids("LEARN_CATEGORY_IDS")
    picked = []
    for channel in channels:
        channel_id = str(channel.get("id", ""))
        if channel.get("type") not in (0, 5):
            continue
        if channel_id in explicit or str(channel.get("parent_id") or "") in categories:
            picked.append({
                "id": channel_id,
                "name": channel.get("name") or channel_id,
                "parent_id": str(channel.get("parent_id") or ""),
            })
    # #bot-test is an output/transcript channel. It may be allowed for live
    # shadow proposals, but its generated messages must never become training
    # or retrieval material for future answers.
    picked = [channel for channel in picked if channel["id"] != OUTPUT_CHANNEL_ID]
    return sorted(picked, key=lambda channel: (channel["name"].lower(), channel["id"]))


def history(channel_id: str, limit: int) -> list[dict]:
    out, before = [], None
    while len(out) < limit:
        batch = _get(
            f"/channels/{channel_id}/messages",
            limit=min(100, limit - len(out)),
            **({"before": before} if before else {}),
        )
        if not batch:
            break
        out.extend(batch)
        before = batch[-1].get("id")
        if len(batch) < 100:
            break
        time.sleep(0.35)
    return list(reversed(out))


def _is_staff(message: dict) -> bool:
    return str((message.get("author") or {}).get("id", "")) in TEAM_IDS


def _record(message: dict, channel: dict, question_context: str) -> dict | None:
    content = scrub((message.get("content") or "").strip())
    if not content:
        return None
    return {
        "id": str(message.get("id", "")),
        "channel_id": channel["id"],
        "channel_name": channel["name"],
        "created_at": message.get("timestamp") or "",
        "is_staff": _is_staff(message),
        "content": content[:1200],
        "question_context": question_context[:800],
        "jump_url": f"https://discord.com/channels/{GUILD_ID}/{channel['id']}/{message.get('id', '')}",
    }


def build(limit: int) -> dict:
    if not TOKEN:
        raise SystemExit("DISCORD_USER_TOKEN is not set in .env")
    channels = channels_to_index()
    if not channels:
        raise SystemExit("No readable configured channels were found")

    records, counts, staff_counts = [], Counter(), Counter()
    for channel in channels:
        messages = history(channel["id"], limit)
        recent_customer_lines: list[str] = []
        for message in messages:
            author = message.get("author") or {}
            if author.get("bot"):
                continue
            content = scrub((message.get("content") or "").strip())
            if not content:
                continue
            if _is_staff(message):
                item = _record(message, channel, " ".join(recent_customer_lines[-3:]))
                if item:
                    records.append(item)
                    staff_counts[channel["name"]] += 1
                recent_customer_lines = []
            else:
                recent_customer_lines.append(content[:800])
                # Keep customer messages too, so retrieval covers the whole
                # configured corpus. Staff replies get a ranking boost later.
                item = _record(message, channel, "")
                if item:
                    records.append(item)
            counts[channel["name"]] += 1
        print(f"  #{channel['name']}: {counts[channel['name']]} messages, {staff_counts[channel['name']]} staff replies")

    records.sort(key=lambda item: item.get("created_at", ""))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "guild_id": GUILD_ID,
        "staff_ids": sorted(TEAM_IDS),
        "channels": channels,
        "message_count": len(records),
        "staff_message_count": sum(1 for item in records if item["is_staff"]),
        "messages": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int,
        default=int(os.getenv("HISTORY_MESSAGES_PER_CHANNEL", "1000")),
        help="maximum messages to fetch per channel",
    )
    parser.add_argument("--scan", action="store_true", help="fetch and report counts without writing")
    args = parser.parse_args()
    payload = build(max(1, args.limit))
    print(f"\ntotal indexed messages: {payload['message_count']}")
    print(f"staff messages indexed: {payload['staff_message_count']}")
    print(f"channels indexed: {len(payload['channels'])}")
    if args.scan:
        print("--scan only, no index written")
        return
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {INDEX_PATH} ({INDEX_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
