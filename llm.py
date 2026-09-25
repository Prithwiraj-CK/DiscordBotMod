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

import json
import logging
import os
import random
import time

import openai
from openai import OpenAI

from usage_reporting import record_usage

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


def _json_max_output_tokens():
    """Bounded output budget for strict routing, research, and draft JSON.

    A strict JSON response can contain several evidence IDs, an answer, and
    validation notes. 500 tokens was occasionally too small for that shape,
    leaving a syntactically incomplete object that the next stage could not
    parse. Keep the value configurable, but never allow an accidental setting
    to make a single support turn unbounded.
    """
    try:
        return min(2_000, max(300, int(os.getenv("LLM_JSON_MAX_OUTPUT_TOKENS", "1200"))))
    except ValueError:
        return 1200


def _retry_delay(attempt):
    """Exponential, jittered retry delay shared by text and JSON calls."""
    return min(2 ** (attempt - 1), 8) + random.uniform(0, 0.5)


def _model_name():
    """The active model is read per call so a restarted service picks up .env."""
    return os.getenv("OPENAI_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"


def _reasoning_effort():
    """Return a supported GPT-6 reasoning effort without trusting a typo in .env."""
    value = os.getenv("OPENAI_REASONING_EFFORT", "medium").strip().lower()
    if value in {"none", "low", "medium", "high", "xhigh", "max"}:
        return value
    log.warning("Unknown OPENAI_REASONING_EFFORT=%r; using medium", value)
    return "medium"


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


def _response_input(messages):
    """Translate the existing chat transcript into Responses API input items.

    Keeping the public ``ask_llm``/``ask_json`` signatures unchanged lets the
    support pipeline move to GPT-6 without weakening its existing evidence and
    validation gates. Images remain remote Discord CDN URLs; no attachment is
    downloaded or persisted by this module.
    """
    items = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            parts = [{
                "type": "output_text" if role == "assistant" else "input_text",
                "text": content,
            }]
        elif isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "text":
                    parts.append({
                        "type": "output_text" if role == "assistant" else "input_text",
                        "text": str(part.get("text") or ""),
                    })
                elif kind == "image_url" and role != "assistant":
                    image = part.get("image_url") or {}
                    url = str(image.get("url") or "").strip()
                    if url:
                        image_part = {"type": "input_image", "image_url": url}
                        detail = image.get("detail")
                        if detail:
                            image_part["detail"] = detail
                        parts.append(image_part)
        else:
            parts = []
        if parts:
            items.append({"role": role, "content": parts})
    return items


def _record_response_usage(response, model):
    """Best-effort accounting must never make a support reply fail."""
    try:
        record_usage(model, getattr(response, "usage", None))
    except Exception:
        log.exception("Could not record OpenAI usage")


def ask_llm(system_prompt, messages):
    """Send a conversation to the model and return its reply text.

    messages is a list of {"role": "user"|"assistant", "content": str}
    entries. For vision calls, content may instead be a text/image-part list,
    oldest first. The function uses the Responses API so GPT-6 Luna can apply
    reasoning; Responses are not stored by OpenAI for this bot.

    Raises LLMUnavailable when the model could not be reached. Callers must
    treat that as "no answer yet" rather than "no answer": a dropped question
    from a real user is the most expensive thing this bot can do.
    """
    attempts = _max_attempts()
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            model = _model_name()
            response = _get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=_response_input(messages),
                max_output_tokens=400,
                reasoning={"effort": _reasoning_effort()},
                store=False,
            )
            _record_response_usage(response, model)
            return (response.output_text or "").strip()

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
            delay = _retry_delay(attempt)
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
    # ``temperature`` remains an accepted argument for compatibility with the
    # callers, but reasoning models do not support it. Their effort setting is
    # the deliberate, supported control instead.
    del temperature
    text_format = {
        "type": "json_schema",
        "name": name,
        "strict": True,
        "schema": schema,
    }

    for attempt in range(1, attempts + 1):
        try:
            model = _model_name()
            response = _get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=_response_input(messages),
                max_output_tokens=_json_max_output_tokens(),
                reasoning={"effort": _reasoning_effort()},
                text={"format": text_format},
                store=False,
            )
            _record_response_usage(response, model)
            content = (response.output_text or "").strip()
            if not content:
                raise ValueError("OpenAI returned an empty structured response")
            try:
                value = json.loads(content)
            except ValueError as exc:
                raise ValueError("OpenAI returned invalid structured JSON") from exc
            if not isinstance(value, dict):
                raise ValueError("OpenAI structured response was not an object")
            return value

        except openai.AuthenticationError as exc:
            raise LLMUnavailable("OpenAI rejected the API key: {}".format(exc)) from exc
        except openai.BadRequestError as exc:
            raise LLMUnavailable("OpenAI rejected the structured request: {}".format(exc)) from exc
        except ValueError as exc:
            # A reasoning model can occasionally exhaust its output budget
            # while emitting a strict object, or return an empty result after
            # internal reasoning. This is transient for a support turn: retry
            # the exact structured request before failing the whole question.
            last_error = exc
            if attempt == attempts:
                break
            delay = _retry_delay(attempt)
            log.warning(
                "Structured model response was incomplete (attempt %s/%s): %s. Retrying in %.1fs",
                attempt, attempts, exc, delay,
            )
            time.sleep(delay)
        except _RETRYABLE as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = _retry_delay(attempt)
            log.warning(
                "Structured model call failed (attempt %s/%s): %s. Retrying in %.1fs",
                attempt, attempts, type(exc).__name__, delay,
            )
            time.sleep(delay)

    raise LLMUnavailable(
        "Structured model unavailable after {} attempts: {}: {}".format(
            attempts, type(last_error).__name__, last_error
        )
    ) from last_error


def ask_json_with_tools(system_prompt, messages, schema, tools, tool_executor,
                        name="tool_research_response", max_tool_rounds=6,
                        require_initial_tool=False):
    """Run a bounded Responses API research loop and return its final JSON.

    ``tool_executor`` is deliberately supplied by the caller.  This module
    owns OpenAI transport/accounting only; the support bot owns the small,
    read-only repository and knowledge tools it is willing to expose.  Each
    model response (including reasoning items) is fed into the next turn with
    its function-call outputs, which is the Responses API pattern required for
    a reasoning model to continue an investigation rather than guess from a
    single fixed evidence packet.
    """
    text_format = {
        "type": "json_schema",
        "name": name,
        "strict": True,
        "schema": schema,
    }
    try:
        rounds = min(10, max(1, int(max_tool_rounds)))
    except (TypeError, ValueError):
        rounds = 6

    input_items = _response_input(messages)
    model = _model_name()
    last_error = None
    for round_number in range(rounds + 1):
        # A product question must begin with a search, while greetings can
        # still receive a normal short reply. Subsequent turns stay automatic
        # so Luna can decide whether another file needs to be opened.
        tool_choice = "required" if round_number == 0 and require_initial_tool else "auto"
        try:
            response = _get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=input_items,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=False,
                max_output_tokens=_json_max_output_tokens(),
                reasoning={"effort": _reasoning_effort()},
                text={"format": text_format},
                store=False,
            )
            _record_response_usage(response, model)
        except openai.AuthenticationError as exc:
            raise LLMUnavailable("OpenAI rejected the API key: {}".format(exc)) from exc
        except openai.BadRequestError as exc:
            raise LLMUnavailable("OpenAI rejected the tool research request: {}".format(exc)) from exc
        except _RETRYABLE as exc:
            last_error = exc
            if round_number >= rounds:
                break
            delay = _retry_delay(round_number + 1)
            log.warning("Tool research request failed: %s. Retrying in %.1fs", type(exc).__name__, delay)
            time.sleep(delay)
            continue

        function_calls = [
            item for item in (getattr(response, "output", None) or [])
            if getattr(item, "type", None) == "function_call"
        ]
        if not function_calls:
            content = (response.output_text or "").strip()
            if not content:
                raise LLMUnavailable("OpenAI ended the research loop without a final response")
            try:
                value = json.loads(content)
            except ValueError as exc:
                raise LLMUnavailable("OpenAI returned invalid tool-loop JSON") from exc
            if not isinstance(value, dict):
                raise LLMUnavailable("OpenAI tool-loop JSON was not an object")
            log.info("Tool research completed after %s tool round(s)", round_number)
            return value

        if round_number >= rounds:
            raise LLMUnavailable("Research tool budget was exhausted before Luna produced an answer")

        log.info(
            "Tool research round %s/%s: %s",
            round_number + 1, rounds,
            ", ".join(str(getattr(call, "name", "unknown")) for call in function_calls),
        )

        # The SDK's Response output objects are valid input items. Keeping all
        # of them (especially reasoning items) is important: omitting them
        # makes later tool calls lose the model's investigation state.
        input_items.extend(getattr(response, "output", None) or [])
        for call in function_calls:
            try:
                arguments = json.loads(getattr(call, "arguments", "{}") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments were not an object")
                result = tool_executor(str(getattr(call, "name", "")), arguments)
            except Exception as exc:  # The model receives a bounded tool error and can recover.
                log.warning("Research tool %s failed: %s", getattr(call, "name", "unknown"), exc)
                result = {"error": "The requested research tool was unavailable for this step."}
            input_items.append({
                "type": "function_call_output",
                "call_id": str(getattr(call, "call_id", "")),
                "output": json.dumps(result, ensure_ascii=False),
            })

    raise LLMUnavailable(
        "Tool research unavailable: {}".format(last_error or "research loop did not finish")
    )


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
