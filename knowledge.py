"""Loads the one-pagers the bot answers from.

Drop a .md file per project into knowledge/ (valhalla.md, olympus.md, ...).
Every file is concatenated into the system prompt, so keep them tight - this
text is sent on every single question.

Edits are picked up without a restart. The files are the fastest lever on
answer quality, so writing one should not mean taking the bot offline.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("support-bot.knowledge")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

_cached_text = ""
_cached_fingerprint: tuple | None = None


def _fingerprint() -> tuple:
    """Cheap "has anything changed" check: name, size and mtime per file.

    Two or three stat() calls per question is nothing next to a model call,
    and it means an edit to a one-pager is live on the next message.
    """
    if not KNOWLEDGE_DIR.is_dir():
        return ()

    entries = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path.name, stat.st_size, stat.st_mtime_ns))
    return tuple(entries)


def _read_all() -> str:
    sections = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            log.warning("Could not read %s, skipping it", path.name)
            continue
        if text:
            sections.append(f"# {path.stem.upper()}\n\n{text}")
    return "\n\n---\n\n".join(sections)


def load_knowledge() -> str:
    """The one-pagers as one string, re-read only when a file has changed."""
    global _cached_text, _cached_fingerprint

    if not KNOWLEDGE_DIR.is_dir():
        return ""

    fingerprint = _fingerprint()
    if fingerprint != _cached_fingerprint:
        _cached_text = _read_all()
        _cached_fingerprint = fingerprint
        log.info(
            "Loaded %s knowledge file(s), %s characters",
            len(fingerprint),
            len(_cached_text),
        )

    return _cached_text
