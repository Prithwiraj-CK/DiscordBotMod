"""Loads the one-pagers the bot answers from.

Drop a .md file per project into knowledge/ (valhalla.md, olympus.md, ...).
Every file is concatenated into the system prompt, so keep them tight - this
text is sent on every single question.

Edits are picked up without a restart. The files are the fastest lever on
answer quality, so writing one should not mean taking the bot offline.
"""

from __future__ import annotations

import logging
import json
from pathlib import Path

log = logging.getLogger("support-bot.knowledge")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
APPROVED_FACTS_PATH = KNOWLEDGE_DIR / "approved_facts.json"

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
    paths = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if APPROVED_FACTS_PATH.exists():
        paths.append(APPROVED_FACTS_PATH)
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path.name, stat.st_size, stat.st_mtime_ns))
    return tuple(entries)


def _read_approved_facts() -> str:
    """Render only approved structured facts for the model context.

    The JSON is deliberately rendered with IDs and provenance. This makes it
    possible to audit an answer later and gives future structured-answer code a
    stable evidence vocabulary, while still keeping the current text prompt
    compatible.
    """
    if not APPROVED_FACTS_PATH.exists():
        return ""

    try:
        payload = json.loads(APPROVED_FACTS_PATH.read_text(encoding="utf-8"))
        facts = payload.get("facts", [])
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        log.error("Could not read approved fact index %s: %s", APPROVED_FACTS_PATH.name, exc)
        return ""

    if not isinstance(facts, list):
        log.error("Approved fact index has a non-list facts field")
        return ""

    lines = [
        "# APPROVED FACTS (AUTHORITATIVE)",
        "Use these facts as the source of truth. A supplemental note below "
        "must not override an approved fact.",
        "Source precedence: product-owner clarification, runtime code, official "
        "product docs, then approved staff examples.",
        "",
    ]
    for fact in sorted(
        (item for item in facts if isinstance(item, dict) and item.get("approved") is True),
        key=lambda item: (str(item.get("product", "")), str(item.get("topic", "")), str(item.get("id", ""))),
    ):
        lines.append(
            "[FACT {id} | product={product} | topic={topic} | action={action} | risk={risk}]".format(
                id=fact.get("id", "unknown"),
                product=fact.get("product", "unknown"),
                topic=fact.get("topic", "unknown"),
                action=fact.get("action", "answer"),
                risk=fact.get("risk", "unknown"),
            )
        )
        lines.append("Fact: {}".format(fact.get("fact", "")))
        if fact.get("answer_guidance"):
            lines.append("Answer guidance: {}".format(fact["answer_guidance"]))
        if fact.get("links"):
            lines.append("Links: {}".format(", ".join(fact["links"])))
        source = fact.get("source") or {}
        lines.append("Evidence: {} — {}".format(source.get("kind", "unknown"), source.get("ref", "unknown")))
        lines.append("")

    return "\n".join(lines).strip()


def _read_all() -> str:
    sections = []
    approved = _read_approved_facts()
    if approved:
        sections.append(approved)

    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        # README contains authoring instructions, not product facts. It should
        # never be sent to the model as if it were customer-facing knowledge.
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            log.warning("Could not read %s, skipping it", path.name)
            continue
        if text:
            sections.append(
                "# SUPPLEMENTAL NOTES — {}\n\n"
                "These notes are secondary. If they conflict with an approved "
                "fact above, use the approved fact.\n\n{}".format(path.stem.upper(), text)
            )
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
