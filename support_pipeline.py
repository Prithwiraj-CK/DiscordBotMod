"""Deterministic support-analysis helpers used before the LLM drafting step.

The functions in this module do not answer product questions from memory. They
identify exact product vocabulary, extract explicitly supplied values, perform
safe arithmetic, and rank already-retrieved evidence.  Repository evidence is
still required before a response can make a product claim.
"""

from __future__ import annotations

import ast
import math
import re
from datetime import datetime, timezone
from typing import Any


PRODUCT_REGISTRY: dict[str, dict[str, Any]] = {
    "olympus": {
        "aliases": ("olympus", "olympusx", "olympus x"),
        "repository_scope": "olympus",
        "features": {
            "copy_trading": {
                "aliases": ("copy trade", "copy trading", "copy-trading", "followed wallet", "copying an address"),
                "labels": (
                    "Ratio %", "Max Trade Size", "Max Market Size", "Max Trades / Market",
                    "Maximum Price Deviation", "Buy Minimum", "Accumulation Buy", "Reverse Copy Mode",
                ),
            },
            "autobond": {"aliases": ("autobond", "bonds", "bond"), "labels": ()},
            "perps": {"aliases": ("perps", "perpetual", "leverage"), "labels": ()},
            "combos": {"aliases": ("combos", "combo"), "labels": ()},
        },
    },
    "valhalla": {
        "aliases": ("valhalla", "valhalla bot"),
        "repository_scope": "valhalla",
        "features": {
            "copy_trading": {
                "aliases": ("dlmm", "damm", "meteora", "copy trade", "copy trading", "follow wallet"),
                "labels": ("Max Trade Size", "Max per Token", "Trade Ratio", "Jupiter Score", "Entry Mode"),
            },
            "onboarding": {"aliases": ("/valhalla start", "settings_dlmm", "phantom"), "labels": ()},
        },
    },
}

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_NUMBER_RE = r"\$?\s*(\d+(?:\.\d+)?)"


def _norm(value: str) -> str:
    return _NORMALIZE_RE.sub(" ", str(value or "").casefold()).strip()


def _contains(text: str, phrase: str) -> bool:
    return _norm(phrase) in _norm(text)


def _terms(text: str, product: str, feature: str) -> tuple[list[str], list[str]]:
    """Return exact interface-label and softer terminology matches."""
    definition = PRODUCT_REGISTRY[product]["features"][feature]
    labels = [label for label in definition["labels"] if _contains(text, label)]
    aliases = [alias for alias in (*PRODUCT_REGISTRY[product]["aliases"], *definition["aliases"])
               if _contains(text, alias)]
    return labels, aliases


def detect_product_feature(text: str, prior_product: str | None = None) -> dict[str, Any]:
    """Use exact UI labels before ambiguous natural-language routing."""
    candidates = []
    for product, product_definition in PRODUCT_REGISTRY.items():
        for feature in product_definition["features"]:
            labels, aliases = _terms(text, product, feature)
            # Exact labels are intentionally decisive. Generic terms such as
            # "market" alone never enter this registry.
            score = len(labels) * 100 + len(aliases) * 12
            if product == prior_product:
                score += 4
            if score:
                candidates.append({
                    "product": product,
                    "feature": feature,
                    "exact_labels": labels,
                    "matched_terms": aliases,
                    "score": score,
                })
    candidates.sort(key=lambda item: (-item["score"], item["product"], item["feature"]))
    selected = candidates[0] if candidates else None
    runner_up = candidates[1] if len(candidates) > 1 else None
    confidence = 0.0
    if selected:
        confidence = 1.0 if selected["exact_labels"] else min(0.92, 0.55 + selected["score"] / 100)
        if runner_up and runner_up["score"] >= selected["score"] * 0.85:
            confidence = min(confidence, 0.65)
    return {
        "product": selected["product"] if selected else "unknown",
        "feature": selected["feature"] if selected else "unknown",
        "confidence": round(confidence, 2),
        "exact_labels": selected["exact_labels"] if selected else [],
        "matched_terms": selected["matched_terms"] if selected else [],
        "candidates": candidates[:6],
    }


def _first_number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return float(match.group(1)) if match else None


def _display_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def extract_question(text: str, detection: dict[str, Any]) -> dict[str, Any]:
    """Extract a strict, non-speculative record from message and OCR text."""
    source = str(text or "")
    lowered = source.casefold()
    values: dict[str, int | float] = {}
    entities = []
    label_to_entity = {
        "ratio %": "ratio_percent",
        "max trade size": "max_trade_size",
        "max market size": "max_market_size",
        "max trades market": "max_trades_per_market",
    }
    for label, entity in label_to_entity.items():
        if _contains(source, label):
            entities.append(entity)

    additional = _first_number(r"(\d+)\s+(?:additional|more)\s+(?:positions?|entries?|opens?)", source)
    per_entry = _first_number(
        r"" + _NUMBER_RE + r"\s*(?:per\s+)?\b(?:position|entry|add|opening)\b",
        source,
    )
    maximum_total = _first_number(r"(?:most\s+(?:i\s+)?(?:wish|want)\s+to\s+spend|maximum(?:\s+total)?|most)\D{0,45}" + _NUMBER_RE, source)
    intended_ratio = _first_number(r"" + _NUMBER_RE + r"\s*percent\s+of\s+(?:aum|the\s+(?:leader|trader).{0,30}position)", source)
    if additional is not None:
        values["additional_entries"] = int(additional)
    if per_entry is not None:
        values["amount_per_entry_usd"] = _display_number(per_entry)
    if maximum_total is not None:
        values["maximum_total_usd"] = _display_number(maximum_total)
    if intended_ratio is not None:
        values["intended_ratio_percent"] = _display_number(intended_ratio)

    screenshot_fields = {
        "visible_ratio_field": r"ratio\s*%\s*(?:(?:currently\s*)?(?:shows?|is|=|:)\s*)?" + _NUMBER_RE,
        "visible_max_trade_size_usd": r"max\s+trade\s+size\s*(?:(?:currently\s*)?(?:shows?|is|=|:)\s*)?" + _NUMBER_RE,
        "visible_max_market_size_usd": r"max\s+market\s+size\s*(?:(?:currently\s*)?(?:shows?|is|=|:)\s*)?" + _NUMBER_RE,
    }
    for field, pattern in screenshot_fields.items():
        value = _first_number(pattern, source)
        if value is not None:
            values[field] = _display_number(value)

    intent = "configure_settings" if detection["feature"] == "copy_trading" and entities else "unknown"
    return {
        "product": detection["product"],
        "feature": detection["feature"],
        "intent": intent,
        "entities": sorted(set(entities)),
        "values": values,
        "required_information": [],
        "missing_information": [],
        "answerable": False,
    }


def calculate(expression: str) -> float:
    """Evaluate arithmetic only; never execute names, calls, or attributes."""
    tree = ast.parse(str(expression), mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
               ast.Pow, ast.USub, ast.UAdd, ast.Constant, ast.Mod, ast.FloorDiv)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("calculation accepts arithmetic only")
    result = eval(compile(tree, "<calculation>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(result, (int, float)) or not math.isfinite(result):
        raise ValueError("calculation result must be finite")
    return float(result)


def percentage_of(amount: float, percent: float) -> float:
    """Return a percentage of an amount with finite-number validation."""
    return calculate("({}) * ({}) / 100".format(float(amount), float(percent)))


def calculate_pnl(entry_price: float, current_price: float, quantity: float, fees_paid: float = 0) -> dict[str, float]:
    """Calculate gross/net PnL and percentage return for a position."""
    entry_value = calculate("({}) * ({})".format(float(entry_price), float(quantity)))
    current_value = calculate("({}) * ({})".format(float(current_price), float(quantity)))
    gross = calculate("({}) - ({})".format(current_value, entry_value))
    net = calculate("({}) - ({})".format(gross, float(fees_paid)))
    percent = calculate("({}) / ({}) * 100".format(gross, entry_value)) if entry_value else 0.0
    return {"gross_pnl": gross, "net_pnl": net, "return_percent": percent}


def calculate_fees_and_net(gross_amount: float, fee_percent: float) -> dict[str, float]:
    """Calculate a percentage fee and the amount remaining after it."""
    fee = percentage_of(gross_amount, fee_percent)
    return {"fee": fee, "net_amount": calculate("({}) - ({})".format(float(gross_amount), fee))}


def calculate_apr(principal: float, return_amount: float, days: float) -> float:
    """Annualize a completed return; a zero/negative duration is invalid."""
    if float(principal) <= 0 or float(days) <= 0:
        raise ValueError("principal and days must be positive")
    return calculate("({}) / ({}) * 365 / ({}) * 100".format(float(return_amount), float(principal), float(days)))


def calculate_stop_take_prices(entry_price: float, stop_loss_percent: float, take_profit_percent: float) -> dict[str, float]:
    """Return long-position stop-loss and take-profit price levels."""
    return {
        "stop_loss_price": calculate("({}) * (1 - ({}) / 100)".format(float(entry_price), float(stop_loss_percent))),
        "take_profit_price": calculate("({}) * (1 + ({}) / 100)".format(float(entry_price), float(take_profit_percent))),
    }


def calculate_position_exposure(entries: list[float]) -> float:
    """Sum independently supplied entry sizes without interpreting account data."""
    return sum(calculate(str(float(entry))) for entry in entries)


def days_until(iso_timestamp: str, now: datetime | None = None) -> float:
    """Return whole/partial days to a timezone-aware ISO market expiration."""
    target = datetime.fromisoformat(str(iso_timestamp).replace("Z", "+00:00"))
    if target.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ValueError("now must include a timezone")
    return (target - reference).total_seconds() / 86400


def calculate_copy_trade_sizing(record: dict[str, Any]) -> dict[str, Any] | None:
    """Calculate reusable per-entry and cumulative copy-trading limits."""
    values = record.get("values", {})
    if record.get("product") != "olympus" or record.get("feature") != "copy_trading":
        return None
    per_entry = values.get("amount_per_entry_usd")
    additional = values.get("additional_entries")
    maximum_total = values.get("maximum_total_usd")
    if per_entry is None or additional is None:
        return None
    total_entries = int(additional) + 1
    inferred_total = total_entries * float(per_entry)
    market_size = float(maximum_total) if maximum_total is not None else inferred_total
    result = {
        "handler": "copy_trade_sizing",
        "total_entries": total_entries,
        "max_trade_size_usd": _display_number(float(per_entry)),
        "max_market_size_usd": _display_number(market_size),
        "max_trades_per_market": total_entries,
        "assumptions": ["The first opening plus the stated additional positions are all in one market."],
        "warnings": [],
    }
    ratio = values.get("intended_ratio_percent")
    shown_ratio = values.get("visible_ratio_field")
    if ratio is not None and shown_ratio is not None and float(ratio) == 1 and float(shown_ratio) == 1000:
        result["warnings"].append("If the intended copy ratio is 1%, enter 1 in Ratio %, not 1000.")
    return result


def calculate_support_values(record: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch deterministic handlers; returns None when no handler applies."""
    calculation = calculate_copy_trade_sizing(record)
    if calculation:
        record["answerable"] = True
        return calculation
    return None


def format_calculation_response(calculation: dict[str, Any]) -> str:
    """Render a verified calculator result without asking the LLM to do maths."""
    if calculation.get("handler") != "copy_trade_sizing":
        return ""
    response = (
        "Set **Max Trade Size** to **${}** so each copied opening is capped at that amount. "
        "Set **Max Market Size** to **${}** for the total exposure in that market. "
        "Set **Max Trades / Market** to **{}** for the initial entry plus the allowed additional entries."
    ).format(
        calculation["max_trade_size_usd"],
        calculation["max_market_size_usd"],
        calculation["max_trades_per_market"],
    )
    if calculation.get("warnings"):
        response += " " + " ".join(calculation["warnings"])
    return response


def rank_evidence(items: list[dict[str, Any]], query: str, detection: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    """Rerank evidence by authority and exact UI terminology before drafting."""
    labels = [_norm(label) for label in detection.get("exact_labels", [])]
    source_weights = {
        "codebase_section": 60,
        "codebase_file": 55,
        "codebase_context": 50,
        "codebase": 42,
        "codebase_structure": 35,
        "codebase_reference": 25,
        "approved_fact": 58,
        # A matched staff Q&A is stronger than unverified chat context, but
        # remains below current code and explicitly approved product facts.
        "staff_history": 48,
        "history": 10,
        "note": 18,
    }
    query_words = {word for word in _norm(query).split() if len(word) > 3}
    ranked = []
    for item in items:
        text = "{} {} {}".format(item.get("source", ""), item.get("fact", ""), item.get("answer_guidance", ""))
        normalized = _norm(text)
        score = source_weights.get(str(item.get("source_type", "")), 20)
        if item.get("approved") is True:
            score = max(score, source_weights["approved_fact"])
        score += sum(4 for word in query_words if word in normalized)
        score += sum(80 for label in labels if label in normalized)
        path = str(item.get("path", "")).casefold()
        if path.endswith((".md", ".mdx")) and "docs" in path:
            score += 18
        if any(part in path for part in ("schema", "settings", "config", "service", "types")):
            score += 12
        copied = dict(item)
        copied["_rank"] = score
        ranked.append(copied)
    ranked.sort(key=lambda item: (-item["_rank"], str(item.get("source", ""))))
    # Do not fill the prompt with repeated isolated hits from one file.
    selected, per_path = [], {}
    for item in ranked:
        path = str(item.get("path") or item.get("source") or item.get("id"))
        if per_path.get(path, 0) >= 2:
            continue
        selected.append(item)
        per_path[path] = per_path.get(path, 0) + 1
        if len(selected) >= max(1, limit):
            break
    return selected


def analysis_log(record: dict[str, Any], calculation: dict[str, Any] | None) -> dict[str, Any]:
    """Return a safe, compact diagnostics record with no message body."""
    return {
        "product": record.get("product"),
        "feature": record.get("feature"),
        "intent": record.get("intent"),
        "entities": record.get("entities", []),
        "values": record.get("values", {}),
        "answerable": record.get("answerable", False),
        "calculation": calculation,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
