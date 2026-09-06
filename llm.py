"""Single choke point for every model call.

Everything else in the bot goes through ask_llm() and does not know or care
which provider is behind it. Swapping OpenAI -> Claude means editing this file
and nothing else.
"""

from __future__ import annotations

import os

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Built on first use, not at import, so .env is loaded by the time we read it."""
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        _client = AsyncOpenAI(api_key=key)
    return _client


async def ask_llm(system_prompt: str, messages: list[dict]) -> str:
    """Send a conversation to the model and return its reply text.

    messages is a list of {"role": "user"|"assistant", "content": str},
    oldest first.
    """
    response = await _get_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "system", "content": system_prompt}, *messages],
        max_tokens=400,
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


# To move to Claude, swap the body above for this and set ANTHROPIC_API_KEY:
#
#     from anthropic import AsyncAnthropic
#     _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
#
#     async def ask_llm(system_prompt: str, messages: list[dict]) -> str:
#         response = await _client.messages.create(
#             model="claude-sonnet-5",
#             system=system_prompt,
#             messages=messages,
#             max_tokens=400,
#         )
#         return response.content[0].text.strip()
