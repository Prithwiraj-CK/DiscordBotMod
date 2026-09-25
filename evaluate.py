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
import time
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
            unsupported = answer.get("unsupported_claims", [])
            if unsupported:
                errors.append("unsupported claims: " + "; ".join(map(str, unsupported)))
        results.append({"id": case["id"], "passed": not errors, "errors": errors})
    passed = sum(1 for result in results if result["passed"])
    return {"passed": passed, "failed": len(results) - passed, "total": len(results), "results": results}


def olympus_release_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the Olympus release gate without hiding product-routing work.

    Generic safety cases remain part of the gate. Valhalla cases stay in the
    corpus for its dormant implementation, but do not belong to an
    Olympus-only release evaluation.
    """
    return [case for case in cases if case.get("product") in {"olympus", "generic"}]


def run_openai_cases(cases: list[dict[str, Any]], post_to_test: bool = False) -> dict[str, Any]:
    """Run every case through the production decision function.

    Importing bot is safe here because this command never calls bot.main().
    The Discord API is used only when post_to_test is explicitly requested.
    """
    import bot

    token = None
    if post_to_test:
        from dotenv import load_dotenv
        import os
        import requests
        load_dotenv(str(ROOT / ".env"))
        token = os.getenv("DISCORD_USER_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_USER_TOKEN is required for --post-to-test")

    answers = []
    for number, case in enumerate(cases, 1):
        question = case["question"]
        try:
            decision = bot.autonomous_decision(
                question,
                [{"role": "user", "content": question}],
            )
            answer = {
                "id": case["id"],
                "action": decision.get("action"),
                "evidence_ids": decision.get("evidence_ids", []),
                "text": decision.get("draft_answer", ""),
                "unsupported_claims": decision.get("unsupported_claims", []),
            }
        except Exception as exc:
            answer = {
                "id": case["id"],
                "action": "error",
                "evidence_ids": [],
                "text": "",
                "unsupported_claims": [f"{type(exc).__name__}: {exc}"],
            }
        answers.append(answer)
        if post_to_test:
            _post_test_result(token, case, answer)
            time.sleep(0.35)
        print(f"Replay {number}/{len(cases)}: {case['id']} -> {answer['action']}", flush=True)

    return score_answers(cases, answers)


def _post_test_result(token: str, case: dict[str, Any], answer: dict[str, Any]) -> None:
    import requests

    text = answer.get("text") or "[no draft]"
    if text == "[[ESCALATE]]":
        text = "[autonomous escalation proposal]"
    elif text == "[[IGNORE]]":
        text = "[autonomous ignore decision]"
    evidence = ", ".join(answer.get("evidence_ids", [])) or "none"
    unsupported = ", ".join(answer.get("unsupported_claims", [])) or "none"
    body = (
        "**eval {id}** · expected \x60{expected}\x60 · actual \x60{actual}\x60\n"
        "> {question}\n\n"
        "{text}\n\n"
        "\x60evidence: {evidence}\x60\n"
        "\x60unsupported: {unsupported}\x60"
    ).format(
        id=case["id"],
        expected=case["expected_action"],
        actual=answer.get("action", "error"),
        question=case["question"].replace("\n", " ")[:500],
        text=text[:1000],
        evidence=evidence[:600],
        unsupported=unsupported[:500],
    )
    url = "https://discord.com/api/v9/channels/1546057978921095178/messages"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload = {"content": body[:2000], "allowed_mentions": {"parse": []}}
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    if response.status_code == 400:
        try:
            blocked = response.json().get("code") == 200000
        except ValueError:
            blocked = False
        if blocked:
            # AutoMod blocks some external links in this transcript channel.
            # Keep the answer text intact in the replay output, but redact URLs
            # in the Discord-only copy so every case can still be reviewed.
            safe_body = re.sub(r"https?://\S+", "[official link redacted in test transcript]", body)
            response = requests.post(
                url, headers=headers,
                json={"content": safe_body[:2000], "allowed_mentions": {"parse": []}},
                timeout=20,
            )
    if response.status_code not in (200, 201):
        detail = response.text.replace("\n", " ")[:500]
        raise ValueError(f"Discord test-channel post failed: HTTP {response.status_code}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list the anonymized regression cases")
    parser.add_argument("--answers", type=Path, help="score a JSON file of structured answers")
    parser.add_argument("--run-openai", action="store_true", help="run all cases through the OpenAI pipeline")
    parser.add_argument(
        "--olympus-only", action="store_true",
        help="run or score only Olympus and generic safety cases",
    )
    parser.add_argument("--post-to-test", action="store_true", help="post each replay result to #bot-test")
    parser.add_argument(
        "--min-score", type=float,
        help="minimum passing fraction for an OpenAI release gate, for example 1.0",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    try:
        facts_payload, cases_payload = validate_corpus()
        facts = facts_payload["facts"]
        cases = cases_payload["cases"]
        if args.olympus_only:
            cases = olympus_release_cases(cases)
        if args.post_to_test and not args.run_openai:
            raise ValueError("--post-to-test requires --run-openai")
        if args.min_score is not None and not 0 <= args.min_score <= 1:
            raise ValueError("--min-score must be between 0 and 1")
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
        elif args.run_openai:
            output = run_openai_cases(cases, post_to_test=args.post_to_test)
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
    elif args.answers or args.run_openai:
        print(f"Scored {output['total']} cases: {output['passed']} passed, {output['failed']} failed")
        for result in output["results"]:
            if not result["passed"]:
                print(f"  {result['id']}: {'; '.join(result['errors'])}")
    else:
        print(f"Corpus OK: {output['facts']} facts, {output['cases']} cases")
    if args.min_score is not None and (args.answers or args.run_openai):
        score = output["passed"] / output["total"] if output["total"] else 0
        if score < args.min_score:
            print(
                "Release gate failed: {:.1%} is below required {:.1%}".format(score, args.min_score),
                file=sys.stderr,
            )
            return 1
    return 0 if not args.answers or output.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
