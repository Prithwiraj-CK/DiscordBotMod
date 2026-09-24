"""Private local accounting and rolling operational usage snapshots.

The ledger deliberately contains only usage counts, model identifiers, and
calculated cost. It never records Discord messages, prompts, completions, API
keys, or webhook URLs. The report is posted only when its separately configured
webhook URL is present.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger("support-bot.usage")

_ROOT = Path(__file__).resolve().parent
_LOCK = threading.RLock()
_UPDATE_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD = None
_UPDATE_THREAD = None
_UPDATE_VERSION = 0
_SECONDS_PER_DAY = 24 * 60 * 60

# USD per million tokens. These are saved with each event so an old report
# remains correct after a future model-price change. Override only when OpenAI
# publishes a changed price and the service has been deliberately updated.
_MODEL_PRICES = {
    "gpt-6-luna": {
        "input": 0.10,
        "cached_input": 0.01,
        "cache_write": 0.125,
        "output": 0.50,
    },
}


def _runtime_path(name):
    configured = os.getenv(name, "").strip()
    if configured:
        return Path(configured).expanduser()
    filename = "openai_usage.jsonl" if name == "USAGE_LEDGER_PATH" else "openai_usage_report_state.json"
    return _ROOT / ".runtime" / filename


def _number(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _field(value, name):
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _usage_counts(usage):
    """Read usage across SDK object and dict shapes without logging content."""
    details = _field(usage, "input_tokens_details")
    output_details = _field(usage, "output_tokens_details")
    cached = _number(_field(details, "cached_tokens"))
    cache_write = _number(
        _field(details, "cache_write_tokens")
        or _field(details, "cache_creation_tokens")
    )
    return {
        "input_tokens": _number(_field(usage, "input_tokens")),
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "output_tokens": _number(_field(usage, "output_tokens")),
        "reasoning_tokens": _number(_field(output_details, "reasoning_tokens")),
    }


def _cost_usd(model, counts):
    prices = _MODEL_PRICES.get(model, {})
    if not prices:
        return None
    cache_write = min(counts["cache_write_tokens"], counts["input_tokens"])
    cached = min(counts["cached_input_tokens"], counts["input_tokens"] - cache_write)
    uncached = max(0, counts["input_tokens"] - cached - cache_write)
    return round(
        uncached * prices["input"] / 1_000_000
        + cached * prices["cached_input"] / 1_000_000
        + cache_write * prices["cache_write"] / 1_000_000
        + counts["output_tokens"] * prices["output"] / 1_000_000,
        8,
    )


def record_usage(model, usage, now=None):
    """Append a sanitized usage event after a successful OpenAI response."""
    if usage is None:
        return
    timestamp = float(time.time() if now is None else now)
    counts = _usage_counts(usage)
    event = {
        "timestamp": timestamp,
        "model": str(model),
        **counts,
        "estimated_cost_usd": _cost_usd(str(model), counts),
    }
    path = _runtime_path("USAGE_LEDGER_PATH")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    except OSError:
        log.exception("Could not write local OpenAI usage ledger")


def _load_events(since, until):
    path = _runtime_path("USAGE_LEDGER_PATH")
    if not path.exists():
        return []
    events = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    timestamp = float(event.get("timestamp", 0))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if since < timestamp <= until:
                    events.append(event)
    except OSError:
        log.exception("Could not read local OpenAI usage ledger")
    return events


def _load_state():
    path = _runtime_path("USAGE_REPORT_STATE_PATH")
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _save_state(state):
    path = _runtime_path("USAGE_REPORT_STATE_PATH")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, separators=(",", ":"))
        temporary.replace(path)
    except OSError:
        log.exception("Could not save usage report state")


def summarize_usage(since, until):
    """Return bounded, display-ready totals for a reporting window."""
    totals = {
        "calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "estimated_cost_usd": 0.0,
        "unknown_cost_calls": 0,
        "models": {},
    }
    for event in _load_events(since, until):
        totals["calls"] += 1
        model = str(event.get("model") or "unknown")
        totals["models"][model] = totals["models"].get(model, 0) + 1
        for field in (
            "input_tokens", "cached_input_tokens", "cache_write_tokens",
            "output_tokens", "reasoning_tokens",
        ):
            totals[field] += _number(event.get(field))
        cost = event.get("estimated_cost_usd")
        if isinstance(cost, (int, float)):
            totals["estimated_cost_usd"] += float(cost)
        else:
            totals["unknown_cost_calls"] += 1
    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)
    return totals


def _format_report(since, until, totals, title="Salena daily OpenAI usage"):
    start = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    end = datetime.fromtimestamp(until, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    model_text = ", ".join(
        "{} ({})".format(model, count)
        for model, count in sorted(totals["models"].items())
    ) or "none"
    # A support message is typically far below one cent. Six decimals keeps a
    # real low cost from looking like $0.0000 in Discord.
    cost = "${:.6f}".format(totals["estimated_cost_usd"])
    if totals["unknown_cost_calls"]:
        cost += " + {} call(s) with unknown model pricing".format(totals["unknown_cost_calls"])
    return (
        "**{}**\n"
        "Window: {} → {}\n"
        "Estimated cost: **{}**\n"
        "Calls: {} · Models: {}\n"
        "Read: {:,} input tokens ({:,} cached; {:,} cache-write)\n"
        "Wrote: {:,} output tokens ({:,} reasoning)"
    ).format(
        title, start, end, cost, totals["calls"], model_text,
        totals["input_tokens"], totals["cached_input_tokens"], totals["cache_write_tokens"],
        totals["output_tokens"], totals["reasoning_tokens"],
    )


def _webhook_wait_url(url):
    """Ask Discord to return the created message ID without exposing the URL."""
    separator = "&" if "?" in url else "?"
    return url + separator + "wait=true"


def _report_payload(since, until, title="Salena daily OpenAI usage"):
    return {
        "content": _format_report(since, until, summarize_usage(since, until), title),
        "allowed_mentions": {"parse": []},
    }


def _post_report(since, until, title):
    """Post one immutable webhook snapshot and return whether it was accepted."""
    url = os.getenv("DAILY_USAGE_WEBHOOK_URL", "").strip()
    if not url:
        return False
    try:
        response = requests.post(
            _webhook_wait_url(url), json=_report_payload(since, until, title), timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as exc:
        log.warning("Could not send usage report: %s", exc)
        return False


def send_due_report(now=None):
    """Create the report message at the start of each 24-hour window."""
    url = os.getenv("DAILY_USAGE_WEBHOOK_URL", "").strip()
    if not url:
        return False
    current = float(time.time() if now is None else now)
    with _LOCK:
        state = _load_state()
        last_report_at = float(state.get("last_report_at", current - _SECONDS_PER_DAY))
        if current - last_report_at < _SECONDS_PER_DAY:
            return False
        # The report always means "the last 24 hours", rather than a period
        # beginning when this particular Discord message was created.
        if not _post_report(current - _SECONDS_PER_DAY, current, "Salena daily OpenAI usage"):
            return False
        _save_state({"last_report_at": current})
        return True


def update_current_report(now=None):
    """Backward-compatible name: publish, never edit, a rolling snapshot."""
    return send_usage_snapshot(now)


def send_usage_snapshot(now=None):
    """Post a new rolling 24-hour snapshot after one completed support turn."""
    current = float(time.time() if now is None else now)
    return _post_report(
        current - _SECONDS_PER_DAY,
        current,
        "Salena OpenAI usage — latest completed response",
    )


def request_usage_report_update():
    """Post after a completed support response without blocking the reply."""
    global _UPDATE_THREAD, _UPDATE_VERSION
    if not os.getenv("DAILY_USAGE_WEBHOOK_URL", "").strip():
        return
    if os.getenv("USAGE_REPORT_LIVE_UPDATES", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    with _UPDATE_LOCK:
        _UPDATE_VERSION += 1
        if _UPDATE_THREAD and _UPDATE_THREAD.is_alive():
            return
        _UPDATE_THREAD = threading.Thread(
            target=_live_update_loop, name="usage-report-update", daemon=True,
        )
        _UPDATE_THREAD.start()


def _live_update_loop():
    """Coalesce completion signals into one new report message per response."""
    global _UPDATE_VERSION
    while not _STOP.is_set():
        # A short coalescing window avoids one webhook edit per internal router,
        # planner, drafter, and validator call while still updating after every
        # user message's response has finished.
        if _STOP.wait(0.35):
            return
        with _UPDATE_LOCK:
            before = _UPDATE_VERSION
        send_usage_snapshot()
        with _UPDATE_LOCK:
            if _UPDATE_VERSION == before:
                return


def start_daily_usage_reporter():
    """Start one lightweight scheduler; sends an initial last-24h report once."""
    global _THREAD
    if not os.getenv("DAILY_USAGE_WEBHOOK_URL", "").strip():
        return
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(target=_report_loop, name="usage-report", daemon=True)
        _THREAD.start()


def _report_loop():
    send_due_report()
    # Polling makes a failed webhook edit retry on the next five-minute
    # interval, without claiming a successful update in the persistent state.
    while not _STOP.wait(300):
        send_due_report()
