"""Regression tests for repository-grounded execution answers."""

import unittest
from unittest.mock import patch

from bot import (
    _historical_product_hint, _known_safe_answer, _repository_products,
    _staff_evidence_answer, _staff_history_evidence, _valhalla_capacity_answer,
)
from codebase_search import _priority_token_queries, _semantic_file_anchors, _workflow_queries
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

    def test_repository_search_prioritises_specific_address_roles(self):
        queries = _priority_token_queries(
            "Why does a new Olympus wallet have signing, trading, and deposit addresses?"
        )
        self.assertEqual(["signing", "trading", "deposit"], queries)

    def test_semantic_file_anchors_select_multiterm_wallet_documentation(self):
        with self.subTest("does not rely on a one-line phrase"):
            # The configured Olympus root is production repository data. This
            # regression checks the generic multi-concept retriever, not a
            # bespoke answer for this question.
            from codebase_search import _root_for
            root = _root_for("olympus")
            if root is None:
                self.skipTest("Olympus repository is not configured")
            anchors = _semantic_file_anchors(
                "Why does a new Olympus wallet have signing, trading, and deposit addresses?",
                "olympus", root, limit=8,
            )
            self.assertTrue(any("WALLET_CREATION.md" in item["path"] for item in anchors))

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

    def test_matching_staff_answer_is_general_evidence_not_raw_history(self):
        evidence = _staff_history_evidence(
            "What does redeemed mean in Olympus?",
            "olympus",
            [{
                "id": "1535011277150359612",
                "is_staff": True,
                "channel_name": "general",
                "question_context": "For Olympus. What does redeemed mean?",
                "content": "Redeeming means claiming your winnings from a resolved market.",
            }],
        )
        self.assertEqual("staff_history.1535011277150359612", evidence[0]["id"])
        self.assertEqual("staff_history", evidence[0]["source_type"])

    def test_staff_history_is_not_evidence_for_a_stuck_redemption(self):
        evidence = _staff_history_evidence(
            "My Olympus redemption is stuck and missing.",
            "olympus",
            [{
                "id": "1535011277150359612",
                "is_staff": True,
                "channel_name": "general",
                "question_context": "For Olympus. What does redeemed mean?",
                "content": "Redeeming means claiming your winnings from a resolved market.",
            }],
        )
        self.assertEqual([], evidence)

    def test_staff_handoff_is_not_promoted_as_an_answer(self):
        evidence = _staff_history_evidence(
            "Can I start Olympus copy trading with only $2?",
            "olympus",
            [{
                "id": "handoff",
                "is_staff": True,
                "channel_name": "general",
                "question_context": "Can I start copy trading with only $2?",
                "content": "Can just wait for a mod to help.",
            }],
        )
        self.assertEqual([], evidence)

    def test_staff_answer_is_retained_as_the_general_fallback(self):
        evidence = _staff_history_evidence(
            "Can I start Olympus copy trading with only $2?",
            "olympus",
            [{
                "id": "minimum-copy",
                "is_staff": True,
                "channel_name": "general",
                "question_context": "Can I start copy trading using $2?",
                "content": (
                    "You can, but $2 will not keep up copying a wallet because "
                    "the minimum market position is $1."
                ),
            }],
        )
        fallback = _staff_evidence_answer(evidence)
        self.assertEqual(["staff_history.minimum-copy"], fallback["evidence_ids"])
        self.assertIn("$2", fallback["answer"])

    @patch("bot.REPOSITORY_SEARCH_BOTH", True)
    def test_repository_research_checks_both_fixed_roots(self):
        self.assertEqual(("olympus", "valhalla"), _repository_products("olympus", "redeemed"))
        self.assertEqual(("valhalla", "olympus"), _repository_products("valhalla", "copy ratio"))


if __name__ == "__main__":
    unittest.main()
