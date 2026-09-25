"""Offline checks for the Olympus-only release gate."""

import sys
import types
import unittest
from unittest.mock import patch

import evaluate


class EvaluateTests(unittest.TestCase):
    def test_olympus_release_cases_excludes_valhalla_and_keeps_generic_safety(self):
        cases = [
            {"id": "olympus", "product": "olympus"},
            {"id": "valhalla", "product": "valhalla"},
            {"id": "generic", "product": "generic"},
        ]
        self.assertEqual(
            ["olympus", "generic"],
            [case["id"] for case in evaluate.olympus_release_cases(cases)],
        )

    def test_openai_replay_does_not_supply_a_product_hint(self):
        calls = []

        def decision(*args, **kwargs):
            calls.append((args, kwargs))
            return {
                "action": "answer",
                "evidence_ids": [],
                "draft_answer": "Olympus answer.",
                "unsupported_claims": [],
            }

        fake_bot = types.SimpleNamespace(autonomous_decision=decision)
        cases = [{
            "id": "olympus.case",
            "question": "What is Olympus?",
            "expected_action": "answer",
            "required_fact_ids": [],
        }]
        with patch.dict(sys.modules, {"bot": fake_bot}):
            result = evaluate.run_openai_cases(cases)
        self.assertEqual(1, result["passed"])
        self.assertEqual({}, calls[0][1])
        self.assertEqual("What is Olympus?", calls[0][0][0])


if __name__ == "__main__":
    unittest.main()
