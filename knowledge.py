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
import re
from pathlib import Path

log = logging.getLogger("support-bot.knowledge")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
APPROVED_FACTS_PATH = KNOWLEDGE_DIR / "approved_facts.json"
HISTORY_INDEX_PATH = Path(__file__).parent / ".runtime" / "discord_history_index.json"
HISTORY_OUTPUT_CHANNEL_ID = "1546057978921095178"

_cached_text = ""
_cached_fingerprint: tuple | None = None
_cached_history_fingerprint: tuple | None = None
_cached_history: list[dict] = []


def load_approved_facts() -> list[dict]:
    """Return approved structured facts for routing and evidence selection."""
    if not APPROVED_FACTS_PATH.exists():
        return []
    try:
        payload = json.loads(APPROVED_FACTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.error("Could not parse approved fact index %s", APPROVED_FACTS_PATH.name)
        return []
    facts = payload.get("facts", []) if isinstance(payload, dict) else []
    return [fact for fact in facts if isinstance(fact, dict) and fact.get("approved") is True]


_FACT_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_FACT_STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "from", "how",
    "i", "in", "is", "it", "my", "of", "on", "or", "the", "this", "to",
    "what", "when", "where", "why", "with", "you", "your",
}


def _fact_tokens(text: str) -> set[str]:
    return {
        token for token in _FACT_TOKEN_RE.findall((text or "").lower())
        if len(token) > 2 and token not in _FACT_STOPWORDS
    }


def retrieve_facts(query: str, product: str | None = None,
                   intent: str | None = None, limit: int = 6) -> list[dict]:
    """Retrieve a small, deterministic evidence set from approved facts.

    Product and intent are supplied by the classifier. Lexical overlap keeps
    this useful even when the classifier is uncertain, while the approved
    index remains the only source eligible for factual answers.
    """
    query_tokens = _fact_tokens(query)
    all_facts = load_approved_facts()
    product_facts = [
        fact for fact in all_facts
        if not product or product in ("unknown", "generic") or fact.get("product") == product
    ]
    topic_facts = [
        fact for fact in product_facts
        if intent and intent != "unknown" and fact.get("topic") == intent
    ]
    candidates = list(topic_facts or product_facts)

    # Account-specific failures often contain a product-topic word such as
    # "order" or "wallet" but need the support-triage fact as well. Keep the
    # topical facts and add the product's escalation guidance for these cases.
    query_lower = (query or "").lower()
    discrepancy_markers = (
        "missing", "duplicat", "mismatch", "wrong", "failed", "stuck",
        "discrepancy", "not there", "check my", "check it", "inspect my", "left over",
    )
    if any(marker in query_lower for marker in discrepancy_markers):
        for fact in product_facts:
            if fact.get("topic") == "support_triage" and fact not in candidates:
                candidates.append(fact)

    # Some words trigger the wrong topic classifier even though the question
    # clearly needs a neighboring fact, such as backtesting plus returns or
    # slippage plus a leftover position.
    related_ids = set()
    if product == "olympus" and "backtest" in query_lower:
        related_ids.update({"olympus.copy_trade.backtesting", "olympus.performance.no_guarantee"})
    if product == "olympus" and re.search(
        r"\b(find|choose|select)\b.*\b(wallet|trader)\b.*\b(copy|follow)\b", query_lower,
    ):
        related_ids.add("olympus.performance.no_guarantee")
    if product == "valhalla" and re.search(
        r"\b(find|where|which)\b.*\b(wallets?|traders?)\b.*\b(follow|copy)\b",
        query_lower,
    ):
        related_ids.add("valhalla.performance.no_guarantee")
    if product == "valhalla" and re.search(r"\b(?:dlmm\s+)?ratio\b", query_lower):
        related_ids.add("valhalla.copy_trade.ratio")
    if product == "valhalla" and re.search(
        r"\bpnl\b.*\b(different|mismatch|wrong)\b|\b(different|mismatch|wrong)\b.*\bpnl\b",
        query_lower,
    ):
        related_ids.add("valhalla.copy_trade.skip_reasons")
    if product == "olympus" and any(marker in query_lower for marker in ("slippage", "left over", "skipped sell", "leader sell")):
        related_ids.update({"olympus.copy_trade.execution_discrepancy", "olympus.copy_trade.behavior"})
    if product == "olympus" and re.search(r"private key|seed phrase|mnemonic", query_lower):
        related_ids.add("olympus.account_specific.escalate")
    if product == "valhalla" and re.search(r"which command.*settings?|mobile.*start|website.*confusing", query_lower):
        related_ids.update({"valhalla.onboarding.commands", "valhalla.onboarding.website"})
    for fact in product_facts:
        if fact.get("id") in related_ids and fact not in candidates:
            candidates.append(fact)

    # Keep adjacent settings out of ratio answers unless the user explicitly
    # asks for them. The ratio fact already explains the relevant comparison;
    # unrelated setting details cause volunteered text.
    if product == "valhalla" and re.search(r"\b(?:dlmm\s+)?ratio\b", query_lower):
        explicit_settings = set()
        if re.search(r"\bmax\s*per[- ]?token\b", query_lower):
            explicit_settings.add("valhalla.settings.max_per_token")
        if re.search(r"\bentry\s*mode\b|\bsol\s*only\b|\bsol_or_usdc\b", query_lower):
            explicit_settings.add("valhalla.settings.entry_mode")
        if re.search(r"\bfilter(?:s|ing)?\b", query_lower):
            explicit_settings.add("valhalla.copy_trade.filters")
        candidates = [
            fact for fact in candidates
            if fact.get("id") == "valhalla.copy_trade.ratio"
            or fact.get("id") in explicit_settings
        ]

    # A sizing question may use two SOL amounts without saying "ratio". The
    # ratio and performance caveat are both relevant evidence in that case.
    if product == "valhalla" and len(re.findall(r"\b\d+(?:\.\d+)?\s*sol\b", query_lower)) >= 2:
        for fact in product_facts:
            if fact.get("id") in {"valhalla.copy_trade.ratio", "valhalla.performance.no_guarantee"} and fact not in candidates:
                candidates.append(fact)
    if product == "valhalla" and "filter" in query_lower:
        for fact in product_facts:
            if fact.get("id") == "valhalla.copy_trade.filters" and fact not in candidates:
                candidates.append(fact)
    if product == "valhalla" and re.search(r"read.?only|untracked", query_lower):
        for fact in product_facts:
            if fact.get("id") == "valhalla.positions.untracked_read_only" and fact not in candidates:
                candidates.append(fact)
    scored = []
    for fact in candidates:
        retrieval_terms = {
            token for token in _fact_tokens(" ".join(fact.get("retrieval_terms", [])))
        }
        if retrieval_terms and not (query_tokens & retrieval_terms):
            continue
        searchable = " ".join(
            str(fact.get(field, ""))
            for field in ("id", "product", "topic", "fact", "answer_guidance")
        )
        fact_tokens = _fact_tokens(searchable)
        overlap = len(query_tokens & fact_tokens)
        score = overlap
        if intent and intent != "unknown" and fact.get("topic") == intent:
            score += 4
        if product == "valhalla" and len(re.findall(r"\b\d+(?:\.\d+)?\s*sol\b", query_lower)) >= 2 and fact.get("id") in {
            "valhalla.copy_trade.ratio", "valhalla.performance.no_guarantee",
        }:
            score += 10
        if fact.get("id") in related_ids:
            score += 10
        if fact.get("action") == "escalate" and any(
            marker in query_tokens for marker in {"my", "missing", "wrong", "failed", "stuck", "discrepancy"}
        ):
            score += 1
        if score > 0:
            scored.append((score, str(fact.get("id", "")), fact))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [fact for _, _, fact in scored[:max(1, limit)]]


def _history_fingerprint() -> tuple:
    try:
        stat = HISTORY_INDEX_PATH.stat()
    except OSError:
        return ()
    return (stat.st_size, stat.st_mtime_ns)


def load_history_index() -> list[dict]:
    """Load the local scrubbed Discord corpus, if it has been built."""
    global _cached_history, _cached_history_fingerprint
    fingerprint = _history_fingerprint()
    if fingerprint == _cached_history_fingerprint:
        return _cached_history
    _cached_history_fingerprint = fingerprint
    _cached_history = []
    if not fingerprint:
        return _cached_history
    try:
        payload = json.loads(HISTORY_INDEX_PATH.read_text(encoding="utf-8"))
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
    except (OSError, json.JSONDecodeError):
        log.warning("Could not parse local Discord history index")
        return _cached_history
    if isinstance(messages, list):
        _cached_history = [item for item in messages if isinstance(item, dict) and item.get("content")]
    log.info("Loaded %s searchable Discord history messages", len(_cached_history))
    return _cached_history


def retrieve_history(query: str, product: str | None = None, limit: int = 4) -> list[dict]:
    """Return a few relevant historical excerpts, with staff replies first.

    Historical text is secondary context only. It can help match how a real
    user asked something and show staff phrasing, but it never replaces
    approved facts as answer authority.
    """
    query_tokens = _fact_tokens(query)
    if not query_tokens:
        return []
    scored = []
    for item in load_history_index():
        # The test channel contains generated eval transcripts, not source
        # support. Never let the bot learn its own drafts as staff examples.
        if str(item.get("channel_id", "")) == HISTORY_OUTPUT_CHANNEL_ID:
            continue
        searchable = " ".join(
            str(item.get(field, ""))
            for field in ("channel_name", "content", "question_context")
        )
        item_tokens = _fact_tokens(searchable)
        overlap = len(query_tokens & item_tokens)
        if not overlap:
            continue
        score = overlap
        if item.get("is_staff"):
            score += 3
        question_tokens = _fact_tokens(str(item.get("question_context", "")))
        score += 2 * len(query_tokens & question_tokens)
        if product in {"valhalla", "olympus"} and product in searchable.lower():
            score += 2
        scored.append((score, str(item.get("created_at", "")), item))
    scored.sort(key=lambda value: (-value[0], value[1]))
    return [item for _, _, item in scored[:max(1, limit)]]


def history_prompt(excerpts: list[dict]) -> str:
    """Render retrieved history as explicitly quoted, secondary context."""
    if not excerpts:
        return ""
    blocks = [
        "# HISTORICAL SUPPORT EXCERPTS (SECONDARY CONTEXT)",
        "These are quoted excerpts retrieved from configured Discord history.",
        "They are not authoritative and may be stale or incomplete. Use them "
        "only to recognize wording and staff style. Never let them override "
        "approved evidence, and never repeat personal data from them.",
        "",
    ]
    for item in excerpts:
        blocks.append("[HISTORY {} | #{} | staff={}]".format(
            item.get("id", "unknown"),
            item.get("channel_name", "unknown"),
            "yes" if item.get("is_staff") else "no",
        ))
        if item.get("question_context"):
            blocks.append("Prior customer wording: {}".format(item["question_context"]))
        blocks.append("Quoted message: {}".format(item.get("content", "")))
        blocks.append("")
    return "\n".join(blocks).strip()


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
