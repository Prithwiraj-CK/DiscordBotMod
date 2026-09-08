"""Single choke point for every model call.

Every model call in the bot goes through this module and does not know or care
which provider is behind it. Swapping OpenAI -> Claude means editing this file
and nothing else.

Synchronous on purpose. The gateway library this bot runs on (discum) is
thread based rather than async, so answers are produced on worker threads and
an async client here would only add a loop to bridge across.

Nothing here reads the environment at import time. bot.py imports this module
before it calls load_dotenv(), so anything read at import would see an empty
.env. Config is read inside the functions instead.
"""

import logging
import json
import os
import random
import time

import openai
from openai import OpenAI

log = logging.getLogger("support-bot.llm")

_client = None

# Transient by nature: the same request a second later usually works. Anything
# not in here (a bad key, a malformed request) fails on the first attempt,
# because retrying it just makes the user wait longer for the same error.
_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class LLMUnavailable(RuntimeError):
    """Every attempt failed. The caller decides what the user sees."""


def _timeout_seconds():
    """Per-attempt budget.

    The SDK default is ten minutes, which in a chat bot means the typing
    indicator spins until the user gives up and leaves. Fail fast and retry.
    """
    try:
        return float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    except ValueError:
        return 30.0


def _temperature():
    """How much the wording varies between calls.

    0.3 is right for a deterministic extractor and wrong for a person: at that
    setting she answers "are you single" with the same sentence every time,
    which reads as a canned response, because it is one. The facts come from
    the reference material and the escalate rules are absolute, so the extra
    variance lands on phrasing rather than content.
    """
    try:
        return float(os.getenv("LLM_TEMPERATURE", "0.9"))
    except ValueError:
        return 0.9


def _max_attempts():
    try:
        return max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


def _get_client():
    """Built on first use, not at import, so .env is loaded by the time we read it."""
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        # max_retries=0 because the retry loop lives in ask_llm. Leaving the
        # SDK's own retries on would multiply the two together, and a request
        # could then outlive the timeout several times over.
        _client = OpenAI(api_key=key, timeout=_timeout_seconds(), max_retries=0)
    return _client


def ask_llm(system_prompt, messages):
    """Send a conversation to the model and return its reply text.

    messages is a list of {"role": "user"|"assistant", "content": str},
    oldest first.

    Raises LLMUnavailable when the model could not be reached. Callers must
    treat that as "no answer yet" rather than "no answer": a dropped question
    from a real user is the most expensive thing this bot can do.
    """
    attempts = _max_attempts()
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = _get_client().chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "system", "content": system_prompt}, *messages],
                max_tokens=400,
                temperature=_temperature(),
            )
            return (response.choices[0].message.content or "").strip()

        except openai.AuthenticationError as exc:
            raise LLMUnavailable("OpenAI rejected the API key: {}".format(exc)) from exc
        except openai.BadRequestError as exc:
            raise LLMUnavailable("OpenAI rejected the request: {}".format(exc)) from exc

        except _RETRYABLE as exc:
            last_error = exc
            if attempt == attempts:
                break
            # Exponential backoff, capped, with jitter so that a burst of
            # questions during an outage does not retry in lockstep.
            delay = min(2 ** (attempt - 1), 8) + random.uniform(0, 0.5)
            log.warning(
                "Model call failed (attempt %s/%s): %s. Retrying in %.1fs",
                attempt, attempts, type(exc).__name__, delay,
            )
            time.sleep(delay)

    raise LLMUnavailable(
        "Model unreachable after {} attempts: {}: {}".format(
            attempts, type(last_error).__name__, last_error
        )
    ) from last_error


def ask_json(system_prompt, messages, schema, name="structured_response", temperature=0.2):
    """Return a model response constrained by an OpenAI JSON schema.

    Routing and evidence selection use this path so the caller can reject an
    unsupported action or citation before anything is posted. It shares the
    same retry and authentication behavior as ask_llm().
    """
    attempts = _max_attempts()
    last_error = None
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }

    for attempt in range(1, attempts + 1):
        try:
            response = _get_client().chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "system", "content": system_prompt}, *messages],
                max_tokens=500,
                temperature=temperature,
                response_format=response_format,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise LLMUnavailable("OpenAI returned an empty structured response")
            try:
                value = json.loads(content)
            except ValueError as exc:
                raise LLMUnavailable("OpenAI returned invalid structured JSON") from exc
            if not isinstance(value, dict):
                raise LLMUnavailable("OpenAI structured response was not an object")
            return value

        except openai.AuthenticationError as exc:
            raise LLMUnavailable("OpenAI rejected the API key: {}".format(exc)) from exc
        except openai.BadRequestError as exc:
            raise LLMUnavailable("OpenAI rejected the structured request: {}".format(exc)) from exc
        except LLMUnavailable:
            raise
        except _RETRYABLE as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = min(2 ** (attempt - 1), 8) + random.uniform(0, 0.5)
            log.warning(
                "Structured model call failed (attempt %s/%s): %s. Retrying in %.1fs",
                attempt, attempts, type(exc).__name__, delay,
            )
            time.sleep(delay)

    raise LLMUnavailable(
        "Structured model unreachable after {} attempts: {}: {}".format(
            attempts, type(last_error).__name__, last_error
        )
    ) from last_error


# To move to Claude, swap the body above for this and set ANTHROPIC_API_KEY:
#
#     from anthropic import Anthropic
#     _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
#
#     def ask_llm(system_prompt, messages):
#         response = _client.messages.create(
#             model="claude-sonnet-5",
#             system=system_prompt,
#             messages=messages,
#             max_tokens=400,
#         )
#         return response.content[0].text.strip()
