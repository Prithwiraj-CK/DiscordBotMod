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
import math
import os
import random
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

import openai
from openai import OpenAI

from usage_reporting import record_usage, usage_counts

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


class ResearchBudgetExceeded(LLMUnavailable):
    """A support turn reached a deterministic resource limit before drafting."""

    def __init__(self, reason):
        self.reason = str(reason)
        super().__init__("Research budget exhausted: {}".format(self.reason))


class ResearchLoopFinished(LLMUnavailable):
    """The raw tool loop is done; the caller must draft from compact evidence."""

    def __init__(self, reason):
        self.reason = str(reason)
        super().__init__("Research loop stopped: {}".format(self.reason))


def _positive_int_env(name, default, minimum=1, maximum=None):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    return min(maximum, value) if maximum is not None else value


_TOKENIZER = None
_TOKENIZER_ATTEMPTED = False


def estimate_tokens(value):
    """Estimate tokens without sending content anywhere.

    ``o200k_base`` is used when tiktoken is installed. Luna does not expose a
    local exact tokenizer, so the fallback reserves one token per three UTF-8
    bytes, deliberately more conservative than ordinary English token ratios.
    """
    global _TOKENIZER, _TOKENIZER_ATTEMPTED
    if value is None:
        return 0
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            value = str(value)
    if not value:
        return 0
    if not _TOKENIZER_ATTEMPTED:
        _TOKENIZER_ATTEMPTED = True
        try:
            import tiktoken
            _TOKENIZER = tiktoken.get_encoding("o200k_base")
        except (ImportError, KeyError, ValueError):
            _TOKENIZER = None
    if _TOKENIZER is not None:
        try:
            return len(_TOKENIZER.encode(value))
        except (TypeError, ValueError):
            pass
    return max(1, int(math.ceil(len(value.encode("utf-8")) / 3)))


@dataclass
class ResearchBudget:
    """Per-support-turn limits and privacy-safe accounting state.

    Each instance belongs to one worker's support turn. ``ContextVar`` below
    prevents concurrent worker threads from sharing counters.
    """

    max_total_input_tokens: int = 50_000
    max_context_tokens: int = 24_000
    max_tool_output_tokens: int = 12_000
    max_tool_calls: int = 10
    max_read_calls: int = 6
    max_evidence_items: int = 8
    max_wall_seconds: float = 75.0
    started_at: float = field(default_factory=time.monotonic)
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_input_tokens: int = 0
    tool_output_tokens: int = 0
    tool_calls: int = 0
    read_calls: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    api_calls: int = 0
    stop_reason: Optional[str] = None

    @classmethod
    def from_environment(cls):
        return cls(
            max_total_input_tokens=_positive_int_env("RESEARCH_MAX_TOTAL_INPUT_TOKENS", 50_000),
            max_context_tokens=_positive_int_env("RESEARCH_MAX_CONTEXT_TOKENS", 24_000),
            max_tool_output_tokens=_positive_int_env("RESEARCH_MAX_TOOL_OUTPUT_TOKENS", 12_000),
            max_tool_calls=_positive_int_env("RESEARCH_MAX_TOOL_CALLS", 10),
            max_read_calls=_positive_int_env("RESEARCH_MAX_READ_CALLS", 6),
            max_evidence_items=_positive_int_env("RESEARCH_MAX_EVIDENCE_ITEMS", 8),
            max_wall_seconds=float(_positive_int_env("RESEARCH_MAX_WALL_SECONDS", 75)),
        )

    def _exhaust(self, reason):
        self.stop_reason = self.stop_reason or str(reason)
        raise ResearchBudgetExceeded(reason)

    def check_time(self):
        if time.monotonic() - self.started_at >= self.max_wall_seconds:
            self._exhaust("time_budget")

    def before_model_call(self, estimated_input):
        self.check_time()
        estimated_input = max(0, int(estimated_input or 0))
        if estimated_input > self.max_context_tokens:
            self._exhaust("context_budget")
        projected = max(self.input_tokens, self.estimated_input_tokens) + estimated_input
        if projected > self.max_total_input_tokens:
            self._exhaust("token_budget")
        self.estimated_input_tokens += estimated_input
        return estimated_input

    def record_response(self, usage, estimated_input=0):
        counts = usage_counts(usage)
        self.api_calls += 1
        self.input_tokens += counts["input_tokens"]
        self.cached_input_tokens += counts["cached_input_tokens"]
        self.output_tokens += counts["output_tokens"]
        self.reasoning_tokens += counts["reasoning_tokens"]
        # Missing SDK usage is uncommon but must not disable the guard.
        if counts["input_tokens"] == 0:
            self.estimated_input_tokens = max(self.estimated_input_tokens, int(estimated_input or 0))
        if self.input_tokens > self.max_total_input_tokens:
            self._exhaust("token_budget")

    def reserve_tool_call(self, name):
        self.check_time()
        if self.tool_calls >= self.max_tool_calls:
            self._exhaust("tool_budget")
        self.tool_calls += 1
        if str(name).startswith("read_"):
            if self.read_calls >= self.max_read_calls:
                self._exhaust("tool_budget")
            self.read_calls += 1

    def record_tool_output(self, payload):
        self.check_time()
        tokens = estimate_tokens(payload)
        if self.tool_output_tokens + tokens > self.max_tool_output_tokens:
            self._exhaust("token_budget")
        self.tool_output_tokens += tokens
        return tokens

    def remaining_tool_output_tokens(self):
        return max(0, self.max_tool_output_tokens - self.tool_output_tokens)

    def remaining_evidence_items(self):
        return max(0, self.max_evidence_items - len(self.evidence_ids))

    def select_evidence(self, items):
        selected = []
        for item in items:
            evidence_id = str(item.get("id") or "")
            if not evidence_id or evidence_id in self.evidence_ids:
                continue
            if len(self.evidence_ids) >= self.max_evidence_items:
                break
            self.evidence_ids.append(evidence_id)
            selected.append(item)
        return selected

    def note_stop(self, reason, replace=False):
        if replace or not self.stop_reason:
            self.stop_reason = str(reason)

    def summary(self):
        return {
            "stop_reason": self.stop_reason or "complete",
            "api_calls": self.api_calls,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "tool_output_tokens": self.tool_output_tokens,
            "tool_calls": self.tool_calls,
            "read_calls": self.read_calls,
            "evidence_ids": list(self.evidence_ids),
        }


_CURRENT_RESEARCH_BUDGET = ContextVar("current_research_budget", default=None)


@contextmanager
def research_budget_scope(budget):
    token = _CURRENT_RESEARCH_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_RESEARCH_BUDGET.reset(token)


def current_research_budget():
    return _CURRENT_RESEARCH_BUDGET.get()


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


def _reserve_model_input(instructions, input_payload, tools=None, text_format=None):
    """Check the active turn before an API call, without retaining content."""
    budget = current_research_budget()
    if budget is None:
        return 0
    estimated = (
        estimate_tokens(instructions)
        + estimate_tokens(input_payload)
        + estimate_tokens(tools)
        + estimate_tokens(text_format)
    )
    return budget.before_model_call(estimated)


def _record_response_usage(response, model, estimated_input=0):
    """Best-effort accounting must never make a support reply fail."""
    try:
        record_usage(model, getattr(response, "usage", None))
    except Exception:
        log.exception("Could not record OpenAI usage")
    budget = current_research_budget()
    if budget is not None:
        budget.record_response(getattr(response, "usage", None), estimated_input)


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
            estimated_input = _reserve_model_input(system_prompt, messages)
            response = _get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=_response_input(messages),
                max_output_tokens=400,
                reasoning={"effort": _reasoning_effort()},
                store=False,
            )
            _record_response_usage(response, model, estimated_input)
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
            estimated_input = _reserve_model_input(system_prompt, messages, text_format=text_format)
            response = _get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=_response_input(messages),
                max_output_tokens=_json_max_output_tokens(),
                reasoning={"effort": _reasoning_effort()},
                text={"format": text_format},
                store=False,
            )
            _record_response_usage(response, model, estimated_input)
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
                        require_initial_tool=False, executor_manages_budget=False):
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
    for round_number in range(rounds):
        # A product question must begin with a search, while greetings can
        # still receive a normal short reply. Subsequent turns stay automatic
        # so Luna can decide whether another file needs to be opened.
        tool_choice = "required" if round_number == 0 and require_initial_tool else "auto"
        # Transport retries belong to this one research operation.  They must
        # not advance ``round_number``: a transient timeout must not turn a
        # useful investigation into a tool-budget exhaustion.
        response = None
        for attempt in range(1, _max_attempts() + 1):
            try:
                estimated_input = _reserve_model_input(
                    system_prompt, input_items, tools=tools, text_format=text_format,
                )
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
                _record_response_usage(response, model, estimated_input)
                break
            except openai.AuthenticationError as exc:
                raise LLMUnavailable("OpenAI rejected the API key: {}".format(exc)) from exc
            except openai.BadRequestError as exc:
                raise LLMUnavailable("OpenAI rejected the tool research request: {}".format(exc)) from exc
            except _RETRYABLE as exc:
                last_error = exc
                if attempt == _max_attempts():
                    break
                delay = _retry_delay(attempt)
                log.warning(
                    "Tool research operation failed (attempt %s/%s): %s. Retrying in %.1fs",
                    attempt, _max_attempts(), type(exc).__name__, delay,
                )
                time.sleep(delay)
        if response is None:
            raise LLMUnavailable(
                "Tool research unavailable: {}".format(last_error or "request failed")
            ) from last_error

        function_calls = [
            item for item in (getattr(response, "output", None) or [])
            if getattr(item, "type", None) == "function_call"
        ]
        if not function_calls:
            # Do not draft from the accumulated raw model/tool transcript.
            # The caller receives this marker and builds one fresh, selected
            # evidence packet for the final writer.
            raise ResearchLoopFinished("complete")

        log.info(
            "Tool research round %s/%s: %s",
            min(round_number + 1, rounds), rounds,
            ", ".join(str(getattr(call, "name", "unknown")) for call in function_calls),
        )

        # The SDK's Response output objects are valid input items. Keeping all
        # of them (especially reasoning items) is important: omitting them
        # makes later tool calls lose the model's investigation state.
        input_items.extend(getattr(response, "output", None) or [])
        for call in function_calls:
            try:
                budget = current_research_budget()
                if budget is not None and not executor_manages_budget:
                    budget.reserve_tool_call(str(getattr(call, "name", "")))
                arguments = json.loads(getattr(call, "arguments", "{}") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments were not an object")
                result = tool_executor(str(getattr(call, "name", "")), arguments)
                if budget is not None and not executor_manages_budget:
                    budget.record_tool_output(result)
            except ResearchBudgetExceeded:
                raise
            except Exception as exc:  # The model receives a bounded tool error and can recover.
                log.warning("Research tool %s failed: %s", getattr(call, "name", "unknown"), exc)
                result = {"error": "The requested research tool was unavailable for this step."}
            input_items.append({
                "type": "function_call_output",
                "call_id": str(getattr(call, "call_id", "")),
                "output": json.dumps(result, ensure_ascii=False),
            })
            # A constrained executor may end the loop after a duplicate call
            # or two no-progress operations.  Still return the normal tool
            # output to the model transcript for observability, then make the
            # caller build the compact final evidence packet.
            stop_reason = result.get("_stop_reason") if isinstance(result, dict) else None
            if stop_reason:
                raise ResearchLoopFinished(str(stop_reason))

        if round_number == rounds - 1:
            raise ResearchLoopFinished("tool_budget")

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
