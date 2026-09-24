"""Regression tests for repository-grounded execution answers."""

import unittest
from unittest.mock import patch

from bot import _historical_product_hint, _known_safe_answer, _valhalla_capacity_answer
from codebase_search import _workflow_queries
from knowledge import retrieve_facts


QUESTION = (
    "If I copy 40% of a leader's position but my balance is too low, "
    "does it skip or use a lower amount?"
)


class RepositoryReasoningTests(unittest.TestCase):
    def test_capacity_question_expands_to_execution_anchors(self):
        queries = _workflow_queries(QUESTION)
        self.assertIn("verifyUserWalletConditions", queries)
        self.assertIn("retryOpenPositionJob", queries)

    @patch("bot.retrieve_history")
    def test_matching_staff_history_routes_to_valhalla_without_becoming_evidence(self, mocked_history):
        mocked_history.return_value = [{
            "is_staff": True,
            "question_context": "For Valhalla DLMM copy trading, does low SOL skip the position?",
            "content": "Valhalla will skip the opening position if your wallet lacks SOL.",
        }]
        self.assertEqual(_historical_product_hint(QUESTION), "valhalla")

    def test_capacity_answer_requires_balance_and_execution_sections(self):
        evidence = [
            {
                "id": "codebase.valhalla.balance.section",
                "source_type": "codebase_section",
                "fact": "verifyUserWalletConditions minimumRequiredBalance",
            },
            {
                "id": "codebase.valhalla.retry.file",
                "source_type": "codebase_file",
                "fact": "retryOpenPositionJob delay: 30000",
            },
            {
                "id": "codebase.valhalla.skip.file",
                "source_type": "codebase_file",
                "fact": "restrictionResult.shouldSkip Skipping position",
            },
        ]
        result = _valhalla_capacity_answer(QUESTION, "valhalla", evidence)
        self.assertIsNotNone(result)
        self.assertIn("does not automatically reduce", result["answer"])
        self.assertEqual(
            result["evidence_ids"],
            [
                "codebase.valhalla.balance.section",
                "codebase.valhalla.retry.file",
                "codebase.valhalla.skip.file",
            ],
        )

    def test_capacity_answer_refuses_one_sided_evidence(self):
        result = _valhalla_capacity_answer(QUESTION, "valhalla", [{
            "id": "codebase.valhalla.balance.section",
            "source_type": "codebase_section",
            "fact": "verifyUserWalletConditions minimumRequiredBalance",
        }])
        self.assertIsNone(result)

    def test_redeemed_definition_is_answerable_but_not_an_account_claim(self):
        question = "What does redeemed mean in Olympus?"
        facts = retrieve_facts(question, product="olympus", intent="unknown", limit=10)
        self.assertIn("olympus.redemption.definition", {item["id"] for item in facts})
        answer = _known_safe_answer(question, "olympus", facts)
        self.assertIn("resolved market", answer)
        self.assertIn("USDC", answer)


if __name__ == "__main__":
    unittest.main()
