"""AI support bot for the project Discord.

Watches a fixed set of channels, answers questions from the one-pagers in
knowledge/, and hands off to a human when it doesn't know.
"""

import logging
import os
import time

import discord
from dotenv import load_dotenv

from knowledge import load_knowledge
from llm import ask_llm

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("support-bot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
STAFF_ROLE_ID = os.getenv("STAFF_ROLE_ID", "").strip()
CONTEXT_MESSAGES = int(os.getenv("CONTEXT_MESSAGES", "8"))
USER_COOLDOWN = float(os.getenv("USER_COOLDOWN_SECONDS", "10"))

ALLOWED_CHANNELS = {
    int(cid)
    for cid in os.getenv("ALLOWED_CHANNEL_IDS", "").replace(" ", "").split(",")
    if cid
}

# The model emits this exact token when it can't answer. We never show it to
# the user - we swap it for a human handoff.
ESCALATE = "[[ESCALATE]]"

SYSTEM_PROMPT = """You are a support assistant in the project's Discord server.

HOW TO ANSWER
- Be brief. Two or three sentences is usually plenty. This is a chat, not a doc.
- Write plainly and casually, the way a helpful teammate would. No corporate tone.
- Answer ONLY from the reference material below. It is your single source of truth.
- Never invent endpoints, parameters, behaviour, timelines, or fixes. If the
  reference doesn't cover it, you don't know it.

WHEN YOU DON'T KNOW
If the reference material doesn't clearly answer the question - or the user is
reporting a bug, asking about their specific account, or asking for something
only a human can action - reply with exactly this and nothing else:
[[ESCALATE]]

Guessing is worse than escalating. Escalate freely.

REFERENCE MATERIAL
{knowledge}
"""

_last_seen: dict[int, float] = {}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def _on_cooldown(user_id: int) -> bool:
    now = time.monotonic()
    if now - _last_seen.get(user_id, 0.0) < USER_COOLDOWN:
        return True
    _last_seen[user_id] = now
    return False


async def _recent_context(channel, upto: discord.Message) -> list[dict]:
    """Last few messages in the channel, oldest first, as model turns."""
    history = [m async for m in channel.history(limit=CONTEXT_MESSAGES, before=upto)]
    turns = []
    for message in reversed(history):
        if not message.content:
            continue
        role = "assistant" if message.author.id == client.user.id else "user"
        content = (
            message.content
            if role == "assistant"
            else f"{message.author.display_name}: {message.content}"
        )
        turns.append({"role": role, "content": content})
    return turns


@client.event
async def on_ready():
    log.info("Connected as %s", client.user)
    if not ALLOWED_CHANNELS:
        log.warning("ALLOWED_CHANNEL_IDS is empty - the bot will not answer anywhere.")
    if not KNOWLEDGE:
        log.warning("knowledge/ is empty - the bot will escalate almost everything.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.channel.id not in ALLOWED_CHANNELS:
        return
    if not message.content.strip():
        return
    if _on_cooldown(message.author.id):
        return

    try:
        async with message.channel.typing():
            turns = await _recent_context(message.channel, message)
            turns.append(
                {"role": "user", "content": f"{message.author.display_name}: {message.content}"}
            )
            answer = await ask_llm(SYSTEM_PROMPT.format(knowledge=KNOWLEDGE), turns)
    except Exception:
        log.exception("Failed to answer message %s", message.id)
        return

    if ESCALATE in answer:
        mention = f"<@&{STAFF_ROLE_ID}> " if STAFF_ROLE_ID else ""
        answer = (
            f"{mention}I'm not sure on this one - hang tight and someone from the "
            f"team will pick it up."
        )

    await message.reply(answer[:2000], mention_author=False)


KNOWLEDGE = load_knowledge()


def _check_config() -> list[str]:
    problems = []
    if not TOKEN:
        problems.append("DISCORD_BOT_TOKEN is not set in .env")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        problems.append("OPENAI_API_KEY is not set in .env")
    if not ALLOWED_CHANNELS:
        problems.append("ALLOWED_CHANNEL_IDS is empty - the bot would answer nowhere")
    return problems


if __name__ == "__main__":
    if problems := _check_config():
        for problem in problems:
            log.error("%s", problem)
        log.error("Fill these in in .env, then run again. See README.md.")
        raise SystemExit(1)

    client.run(TOKEN, log_handler=None)
