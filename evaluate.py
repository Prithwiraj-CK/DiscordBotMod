"""Validate the approved support corpus and score structured answer fixtures.

This command is intentionally offline. It never calls OpenAI or Discord.

Examples:
    python evaluate.py
    python evaluate.py --list
    python evaluate.py --answers answers.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
FACTS_PATH = ROOT / "knowledge" / "approved_facts.json"
CASES_PATH = ROOT / "knowledge" / "eval_cases.json"
ALLOWED_ACTIONS = {"answer", "clarify", "escalate", "ignore"}
ALLOWED_FACT_ACTIONS = {"answer", "escalate"}
REQUIRED_FACT_FIELDS = {
    "id",
    "product",
    "topic",
    "action",
    "fact",
    "source",
    "last_verified",
    "risk",
    "approved",
}
SENSITIVE_PATTERNS = (
    re.compile(r"DISCORD_(?:USER_)?TOKEN", re.IGNORECASE),
    re.compile(r"OPENAI_API_KEY", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]+-----"),
    re.compile(r"\b(?:private key|seed phrase|mnemonic)\s*[:=]", re.IGNORECASE),
)


def load_json(path: Path) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    return value


def validate_corpus() -> tuple[dict[str, Any], dict[str, Any]]:
    facts_payload = load_json(FACTS_PATH)
    cases_payload = load_json(CASES_PATH)
    if not isinstance(facts_payload, dict) or not isinstance(cases_payload, dict):
        raise ValueError("corpus files must contain JSON objects")
    if facts_payload.get("schema_version") != 1:
        raise ValueError("approved_facts.json must use schema_version 1")
    if cases_payload.get("schema_version") != 1:
        raise ValueError("eval_cases.json must use schema_version 1")

    facts = facts_payload.get("facts")
    cases = cases_payload.get("cases")
    if not isinstance(facts, list) or not facts:
        raise ValueError("approved_facts.json must contain a non-empty facts list")
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval_cases.json must contain a non-empty cases list")

    fact_ids: set[str] = set()
    for index, fact in enumerate(facts, 1):
        if not isinstance(fact, dict):
            raise ValueError(f"fact {index} must be an object")
        missing = REQUIRED_FACT_FIELDS - fact.keys()
        if missing:
            raise ValueError(f"fact {index} missing fields: {', '.join(sorted(missing))}")
        fact_id = fact["id"]
        if not isinstance(fact_id, str) or not fact_id:
            raise ValueError(f"fact {index} has an invalid id")
        if fact_id in fact_ids:
            raise ValueError(f"duplicate fact id: {fact_id}")
        fact_ids.add(fact_id)
        if fact["action"] not in ALLOWED_FACT_ACTIONS:
            raise ValueError(f"fact {fact_id} has invalid action: {fact['action']}")
        if fact["approved"] is not True:
            raise ValueError(f"fact {fact_id} is not approved")
        if not isinstance(fact["source"], dict) or not fact["source"].get("kind"):
            raise ValueError(f"fact {fact_id} needs a source kind")
        serialized = json.dumps(fact, ensure_ascii=False)
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(serialized):
                raise ValueError(f"fact {fact_id} contains a sensitive-looking value")

    case_ids: set[str] = set()
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        for field in ("id", "question", "expected_action", "product", "risk", "required_fact_ids"):
            if not case.get(field) and field != "required_fact_ids":
                raise ValueError(f"case {index} missing field: {field}")
        case_id = case["id"]
        if case_id in case_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)
        if case["expected_action"] not in ALLOWED_ACTIONS:
            raise ValueError(f"case {case_id} has invalid expected_action")
        if not isinstance(case["required_fact_ids"], list):
            raise ValueError(f"case {case_id} required_fact_ids must be a list")
        unknown = set(case["required_fact_ids"]) - fact_ids
        if unknown:
            raise ValueError(f"case {case_id} references unknown facts: {', '.join(sorted(unknown))}")
        if not isinstance(case.get("forbidden_claims", []), list):
            raise ValueError(f"case {case_id} forbidden_claims must be a list")

    return facts_payload, cases_payload


def score_answers(cases: list[dict[str, Any]], answers: Any) -> dict[str, Any]:
    if isinstance(answers, dict):
        answers = answers.get("answers")
    if not isinstance(answers, list):
        raise ValueError("answers file must contain an array or an object with an answers array")
    by_id = {item.get("id"): item for item in answers if isinstance(item, dict)}
    results = []
    for case in cases:
        answer = by_id.get(case["id"])
        errors: list[str] = []
        if answer is None:
            errors.append("missing answer")
        else:
            if answer.get("action") != case["expected_action"]:
                errors.append(f"action={answer.get('action')!r}, expected={case['expected_action']!r}")
            evidence = set(answer.get("evidence_ids", []))
            missing = set(case["required_fact_ids"]) - evidence
            if missing:
                errors.append(f"missing evidence: {', '.join(sorted(missing))}")
            text = str(answer.get("text", ""))
            lowered = text.casefold()
            forbidden = [claim for claim in case.get("forbidden_claims", []) if claim.casefold() in lowered]
            if forbidden:
                errors.append(f"forbidden claims: {', '.join(forbidden)}")
        results.append({"id": case["id"], "passed": not errors, "errors": errors})
    passed = sum(1 for result in results if result["passed"])
    return {"passed": passed, "failed": len(results) - passed, "total": len(results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list the anonymized regression cases")
    parser.add_argument("--answers", type=Path, help="score a JSON file of structured answers")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    try:
        facts_payload, cases_payload = validate_corpus()
        facts = facts_payload["facts"]
        cases = cases_payload["cases"]
        if args.list:
            output: Any = [
                {
                    "id": case["id"],
                    "action": case["expected_action"],
                    "product": case["product"],
                    "intent": case.get("intent"),
                    "question": case["question"],
                }
                for case in cases
            ]
        elif args.answers:
            output = score_answers(cases, load_json(args.answers))
        else:
            output = {
                "status": "ok",
                "facts": len(facts),
                "cases": len(cases),
                "approved_facts": sum(1 for fact in facts if fact.get("approved") is True),
            }
    except (OSError, TypeError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(output, indent=2))
    elif args.list:
        for case in output:
            print(f"{case['id']} [{case['action']}/{case['product']}/{case['intent']}]: {case['question']}")
    elif args.answers:
        print(f"Scored {output['total']} cases: {output['passed']} passed, {output['failed']} failed")
        for result in output["results"]:
            if not result["passed"]:
                print(f"  {result['id']}: {'; '.join(result['errors'])}")
    else:
        print(f"Corpus OK: {output['facts']} facts, {output['cases']} cases")
    return 0 if not args.answers or output.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
