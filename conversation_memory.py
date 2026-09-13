"""Short-lived, scoped conversation memory for Salena.

Redis is deliberately optional. If it is not configured, missing, unavailable,
or contains malformed data, callers receive an empty context and the bot keeps
using its existing Discord history path.

This is conversation context, not product knowledge. Values from this store
must never override approved facts or repository evidence.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone


log = logging.getLogger("support-bot.memory")

try:
    import redis
except ImportError:  # pragma: no cover - exercised by the optional fallback
    redis = None


_SECRET_RE = re.compile(
    r"(?i)(?:private\s*key|seed\s*phrase|mnemonic|api\s*key|access\s*token|"
    r"refresh\s*token|password|passcode|secret)\s*[:=]\s*\S+"
)
_LONG_HEX_RE = re.compile(r"\b[0-9a-f]{48,}\b", re.IGNORECASE)
_BASE58_SECRET_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{80,}\b")
_WHITESPACE_RE = re.compile(r"\s+")


def _env_int(name, default, minimum=1):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        log.warning("%s=%r is not a whole number, using %s", name, raw, default)
        return default


def _scrub(text, max_chars):
    """Keep context useful while preventing obvious secret material in Redis."""
    value = _WHITESPACE_RE.sub(" ", str(text or "")).strip()
    if not value:
        return ""
    value = _SECRET_RE.sub("[redacted]", value)
    value = _LONG_HEX_RE.sub("[redacted]", value)
    value = _BASE58_SECRET_RE.sub("[redacted]", value)
    return value[:max_chars]


class ConversationMemory:
    """A small Redis-backed JSON record per conversation participant."""

    def __init__(self):
        self.enabled = os.getenv("CONVERSATION_MEMORY_ENABLED", "true").strip().lower() in (
            "1", "true", "yes", "on",
        )
        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self.prefix = os.getenv("REDIS_KEY_PREFIX", "salena:conversation").strip() or "salena:conversation"
        self.ttl_seconds = _env_int("CONVERSATION_TTL_SECONDS", 4 * 60 * 60)
        self.max_turns = _env_int("CONVERSATION_MAX_TURNS", 32, minimum=4)
        self.max_chars = _env_int("CONVERSATION_MAX_CHARS", 18000, minimum=1000)
        self.max_context_chars = _env_int("CONVERSATION_CONTEXT_MAX_CHARS", 12000, minimum=1000)
        self.summary_max_chars = _env_int("CONVERSATION_SUMMARY_MAX_CHARS", 3000, minimum=500)
        self._client = None
        self._warned = False

        if not self.enabled or not self.redis_url:
            return
        if redis is None:
            self._warn_once("Redis memory is configured but the redis Python package is not installed")
            return
        try:
            self._client = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=2.5,
                health_check_interval=30,
            )
            self._client.ping()
            log.info(
                "Short-term conversation memory enabled (%ss TTL, %s-turn cap)",
                self.ttl_seconds, self.max_turns,
            )
        except Exception as exc:
            self._client = None
            self._warn_once("Redis memory unavailable; continuing without it: %s", exc)

    @property
    def available(self):
        return self._client is not None

    def _warn_once(self, message, *args):
        if not self._warned:
            self._warned = True
            log.warning(message, *args)

    def key(self, guild_id, channel_id, thread_id, user_id):
        """Scope memory so unrelated users and tickets cannot share context."""
        parts = [guild_id, channel_id, thread_id, user_id]
        safe = [re.sub(r"[^0-9A-Za-z:_-]", "_", str(part or "unknown")) for part in parts]
        return "{}:{}".format(self.prefix, ":".join(safe))

    def _lock(self, key):
        if not self._client:
            return None
        return self._client.lock(
            key + ":lock", timeout=5, blocking_timeout=1,
        )

    def _read(self, key):
        if not self._client:
            return {"summary": "", "turns": []}
        try:
            raw = self._client.get(key)
            if not raw:
                return {"summary": "", "turns": []}
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("turns"), list):
                raise ValueError("record is not a conversation object")
            turns = []
            for turn in payload["turns"]:
                if not isinstance(turn, dict):
                    continue
                role = turn.get("role")
                content = _scrub(turn.get("content"), self.max_chars)
                if role not in ("user", "assistant") or not content:
                    continue
                turns.append({
                    "role": role,
                    "content": content,
                    "message_id": str(turn.get("message_id") or ""),
                })
            return {
                "summary": _scrub(payload.get("summary"), self.summary_max_chars),
                "turns": turns,
            }
        except Exception as exc:
            self._warn_once("Could not read Redis conversation memory; disabling it: %s", exc)
            self._client = None
            return {"summary": "", "turns": []}

    def _write(self, key, payload):
        if not self._client:
            return False
        try:
            self._client.setex(key, self.ttl_seconds, json.dumps(payload, separators=(",", ":")))
            return True
        except Exception as exc:
            self._warn_once("Could not write Redis conversation memory; disabling it: %s", exc)
            self._client = None
            return False

    def _compact(self, payload):
        turns = payload["turns"]
        summary = payload.get("summary", "")
        total_chars = sum(len(turn["content"]) for turn in turns)
        while (len(turns) > self.max_turns or total_chars > self.max_chars) and turns:
            old = turns.pop(0)
            total_chars -= len(old["content"])
            label = "user" if old["role"] == "user" else "Salena"
            line = "{}: {}".format(label, old["content"])
            summary = _scrub(
                (summary + "\n" + line).strip(), self.summary_max_chars,
            )
        payload["summary"] = summary
        return payload

    def append(self, scope, role, content, message_id=""):
        """Upsert one scoped turn and refresh the four-hour TTL."""
        if not self._client or role not in ("user", "assistant"):
            return False
        cleaned = _scrub(content, self.max_chars)
        if not cleaned:
            return False
        key = self.key(**scope)
        lock = self._lock(key)
        if lock is None:
            return False
        try:
            with lock:
                payload = self._read(key)
                message_id = str(message_id or "")
                replacement = False
                if message_id:
                    for turn in payload["turns"]:
                        if turn.get("message_id") == message_id:
                            turn.update({"role": role, "content": cleaned})
                            replacement = True
                            break
                if not replacement:
                    payload["turns"].append({
                        "role": role,
                        "content": cleaned,
                        "message_id": message_id,
                    })
                self._compact(payload)
                return self._write(key, payload)
        except Exception as exc:
            self._warn_once("Could not update Redis conversation memory; disabling it: %s", exc)
            self._client = None
            return False

    def load(self, scope):
        """Return safe model turns, with summary first and newest turns retained."""
        if not self._client:
            return []
        key = self.key(**scope)
        payload = self._read(key)
        summary = payload.get("summary", "")
        turns = payload.get("turns", [])
        result = []
        if summary:
            result.append({
                "role": "user",
                "content": "[SHORT-TERM CONVERSATION SUMMARY, CONTEXT ONLY]\n{}".format(summary),
            })
        used = len(result[0]["content"]) if result else 0
        for turn in reversed(turns):
            size = len(turn["content"])
            if used + size > self.max_context_chars:
                break
            result.insert(1 if summary else 0, {
                "role": turn["role"],
                "content": turn["content"],
            })
            used += size
        return result

    def rememberable(self, message):
        """Whether a gateway message can be safely recorded as user context."""
        author = message.get("author") or {}
        if author.get("bot") or not str(author.get("id") or ""):
            return False
        return bool((message.get("content") or "").strip() or message.get("attachments"))

    def status(self):
        if not self.enabled:
            return "disabled"
        if not self.redis_url:
            return "not configured"
        if not redis:
            return "package missing"
        return "available" if self.available else "unavailable"
