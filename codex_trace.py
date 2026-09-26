"""Privacy-safe, opt-in delivery of hosted-agent lifecycle events.

This deliberately sends structured metadata rather than application log lines.
Discord questions, model output, repository text, credentials, session IDs, and
filesystem paths are never accepted as trace fields.
"""

from __future__ import annotations

import os
import re
import threading
import logging
from urllib.parse import urlparse

import requests


log = logging.getLogger("support-bot.codex-trace")

_SAFE_FIELD_RE = re.compile(r"[^A-Za-z0-9_.:/=-]+")
_MAX_FIELDS = 8
_MAX_VALUE_CHARS = 120
_ALLOWED_FIELDS = {
    "archive_bytes", "compressed_bytes", "error_code", "event_type",
    "evidence_count", "inline_files", "reason", "result_type",
    "runtime", "sandbox_calls", "selected_files", "source_bytes", "status",
}

_EVENT_HEADLINES = {
    "runtime_configured": "Hosted Codex research is enabled.",
    "snapshot_constructed": "Olympus workspace prepared.",
    "snapshot_prepared": "Secure workspace upload prepared.",
    "snapshot_request_accepted": "OpenAI accepted the workspace upload.",
    "session_created": "A hosted Codex session was created.",
    "environment_connected": "The isolated workspace is ready.",
    "investigation_started": "Codex started checking Olympus code.",
    "repository_activity_detected": "Codex is searching the Olympus snapshot.",
    "investigation_completed": "Codex finished its investigation.",
    "evidence_validated": "Evidence checks passed.",
    "returning_to_shadowmode": "A verified result was passed to Salena for posting.",
    "investigation_failed": "The hosted investigation stopped before it returned verified evidence.",
    "responses_fallback": "Hosted research was unavailable; the backup research path was used.",
    "research_abstained": "Research stopped safely without guessing; Salena will hand off.",
    "snapshot_aborted": "The safe Olympus workspace was unavailable. No hosted session was started.",
}


def _webhook_url() -> str | None:
    raw = os.getenv("CODEX_TRACE_WEBHOOK_URL", "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
        or not parsed.path.startswith("/api/webhooks/")
    ):
        return None
    return raw


def _safe_value(value: object) -> str:
    """Keep only compact identifier/count-like values in remote trace posts."""
    rendered = _SAFE_FIELD_RE.sub("_", str(value or "")).strip("_")
    return rendered[:_MAX_VALUE_CHARS] or "none"


def _count(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _size(value: object) -> str:
    amount = _count(value)
    if amount < 1024 * 1024:
        return "{:,} KB".format(max(1, round(amount / 1024)))
    return "{:.1f} MB".format(amount / (1024 * 1024))


def _human_content(event: str, fields: dict) -> str:
    """Render a privacy-safe lifecycle update for non-technical operators."""
    normalized = _safe_value(event)
    lines = ["**Salena research update**", _EVENT_HEADLINES.get(normalized, "Research status updated.")]
    if normalized == "snapshot_constructed":
        lines.append(
            "Prepared {:,} approved files ({} source, {} upload).".format(
                _count(fields.get("selected_files")), _size(fields.get("source_bytes")),
                _size(fields.get("archive_bytes")),
            )
        )
    elif normalized == "snapshot_prepared":
        lines.append("Upload split into {} secure part(s).".format(_count(fields.get("inline_files"))))
    elif normalized == "evidence_validated":
        lines.append("{} supporting source(s) passed the evidence check.".format(_count(fields.get("evidence_count"))))
        lines.append("Sandbox tool calls used: {}.".format(_count(fields.get("sandbox_calls"))))
    elif normalized == "returning_to_shadowmode":
        lines.append("Result type: {}. Sources checked: {}.".format(
            "answer" if fields.get("result_type") == "answer" else "follow-up needed",
            _count(fields.get("evidence_count")),
        ))
    return "\n".join(lines)


def _deliver(webhook_url: str, content: str) -> None:
    try:
        response = requests.post(webhook_url, json={"content": content}, timeout=5)
        log.info("[CODEX] trace webhook delivery status=%s", getattr(response, "status_code", "unknown"))
    except requests.RequestException:
        # A diagnostics destination must never affect a support response and
        # must never log a URL or an error body that could contain secrets.
        log.warning("[CODEX] trace webhook delivery failed")


def emit(event: str, **fields: object) -> None:
    """Best-effort asynchronous trace post with a strict metadata-only schema."""
    webhook_url = _webhook_url()
    if webhook_url is None:
        return
    safe_fields = {
        key: value for key, value in fields.items()
        if key in _ALLOWED_FIELDS
    }
    thread = threading.Thread(
        target=_deliver, args=(webhook_url, _human_content(event, safe_fields)), daemon=True,
        name="codex-trace-webhook",
    )
    thread.start()
