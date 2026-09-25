"""Regression tests for repository-grounded execution answers."""

import unittest
from unittest.mock import patch

from bot import (
    _deterministic_research_failures,
    _historical_product_hint, _known_safe_answer, _luna_conversation_window,
    _repository_products, _requires_account_handoff, _staff_evidence_answer,
    _staff_history_evidence, _valhalla_capacity_answer, autonomous_decision,
)
from codebase_search import (
    _priority_token_queries, _section_bounds, _semantic_file_anchors,
    _workflow_queries,
)
from knowledge import retrieve_facts


QUESTION = (
    "If I copy 40% of a leader's position but my balance is too low, "
    "does it skip or use a lower amount?"
)


class RepositoryReasoningTests(unittest.TestCase):
    def test_general_product_question_cannot_escalate_after_research(self):
        draft = {
            "action": "escalate", "evidence_ids": ["repo.wallet.section"],
            "claim_evidence": [], "draft_answer": "",
        }
        failures, _ = _deterministic_research_failures(
            "Why does a new Olympus wallet have signing and trading addresses?",
            draft, {"repo.wallet.section"}, factual_question=True,
        )
        self.assertIn("A general product question must be answered, not handed off.", failures)

    def test_deterministic_gate_accepts_grounded_general_answer(self):
        draft = {
            "action": "answer", "evidence_ids": ["repo.wallet.section"],
            "claim_evidence": [{"claim": "The signing address authorizes actions.", "evidence_ids": ["repo.wallet.section"]}],
            "draft_answer": "The signing address authorizes actions.",
        }
        failures, used = _deterministic_research_failures(
            "Why does a new Olympus wallet have signing and trading addresses?",
            draft, {"repo.wallet.section"}, factual_question=True,
        )
        self.assertEqual([], failures)
        self.assertEqual({"repo.wallet.section"}, used)

    def test_luna_window_keeps_five_prior_user_messages(self):
        turns = []
        for index in range(7):
            turns.append({"role": "user", "content": "user message {}".format(index)})
            turns.append({"role": "assistant", "content": "answer {}".format(index)})
        turns.append({"role": "user", "content": "current question"})

        window = _luna_conversation_window(turns, max_turns=4)

        user_messages = [turn["content"] for turn in window if turn["role"] == "user"]
        self.assertEqual("current question", user_messages[-1])
        self.assertGreaterEqual(len(user_messages[:-1]), 5)

    def test_luna_window_prefers_the_current_user_over_channel_bystanders(self):
        turns = [
            {"role": "user", "content": "Billi: my earlier question {}".format(index)}
            for index in range(6)
        ]
        turns.extend(
            {"role": "user", "content": "Other{}: unrelated chat".format(index)}
            for index in range(6)
        )
        turns.append({"role": "user", "content": "Billi: current question"})

        window = _luna_conversation_window(turns, max_turns=4)
        billi_messages = [
            turn for turn in window
            if turn["role"] == "user" and turn["content"].startswith("Billi:")
        ]
        self.assertGreaterEqual(len(billi_messages[:-1]), 5)

    def test_hypothetical_low_balance_behavior_is_not_an_account_handoff(self):
        self.assertFalse(_requires_account_handoff(QUESTION))
        self.assertTrue(_requires_account_handoff("My Valhalla balance is missing, can you check it?"))

    def test_capacity_question_expands_to_execution_anchors(self):
        queries = _workflow_queries(QUESTION)
        self.assertIn("verifyUserWalletConditions", queries)
        self.assertIn("retryOpenPositionJob", queries)

    def test_leader_follower_order_expands_to_watcher_anchors(self):
        queries = _workflow_queries(
            "Can the copying wallet open before the lead wallet enters the pool?"
        )
        self.assertIn("processUserForCopyTrade", queries)
        self.assertIn("copyTradeQueue.add", queries)

    def test_multiline_typescript_method_reads_the_complete_scope(self):
        lines = [
            "class Watcher {",
            "  private async processTransaction(",
            "    signature: string,",
            "    wallet: string,",
            "  ): Promise<void> {",
            "    if (wallet) {",
            "      await this.enqueue(signature);",
            "    }",
            "  }",
            "}",
        ]
        self.assertEqual((2, 9), _section_bounds(lines, 7, ".ts"))

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

    def test_wallet_address_roles_include_the_default_deposit_mapping(self):
        question = "Why does a new Olympus wallet have signing, trading, and deposit addresses?"
        facts = retrieve_facts(question, product="olympus", intent="wallets", limit=10)
        fact = next(item for item in facts if item["id"] == "olympus.wallets.address_roles")
        self.assertIn("deposit wallet address", fact["fact"])
        self.assertIn("signing address authorizes", fact["answer_guidance"])

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

    @patch("bot._review_evidence")
    @patch("bot._plan_searches", return_value=[])
    @patch("bot.retrieve_history")
    @patch("bot.retrieve_notes", return_value=[])
    @patch("bot.retrieve_facts", return_value=[])
    @patch("bot.read_codebase_section")
    @patch("bot.search_codebase")
    @patch("bot.ask_json_with_tools")
    @patch("bot.ask_json")
    @patch("bot.CODEBASE_SEARCH_ENABLED", True)
    @patch("bot.APPROVED_FACTS_ENABLED", False)
    @patch("bot.REPOSITORY_SEARCH_BOTH", True)
    def test_luna_pipeline_does_not_post_a_loose_staff_reply(
        self,
        mocked_ask,
        mocked_agent,
        mocked_search,
        mocked_read,
        mocked_facts,
        mocked_notes,
        mocked_history,
        mocked_plan,
        mocked_review,
    ):
        del mocked_facts, mocked_notes, mocked_plan
        question = (
            "Does the lead wallet need to enter the pool before the copying "
            "wallet opens its position?"
        )
        source = {
            "id": "codebase.valhalla.copy-order",
            "source_type": "codebase_section",
            "product": "valhalla",
            "source": "copy-trade-transaction-watcher.ts:260-620",
            "path": "src/scripts/copy-trade/copy-trade-transaction-watcher.ts",
            "line": 260,
            "fact": (
                "The watcher observes and resolves the target wallet transaction first, "
                "then processUserForCopyTrade enqueues each follower's copy job."
            ),
        }
        mocked_search.side_effect = lambda query, product, limit=28: [source] if product == "valhalla" else []
        mocked_read.return_value = source
        mocked_history.return_value = [{
            "id": "bad-old-answer",
            "is_staff": True,
            "channel_name": "general",
            "question_context": "copy wallet pool lead wallet",
            "content": "close that position, doesnt stop copying the wallet",
        }]
        mocked_review.return_value = {
            "needs_more_search": False,
            "follow_up_searches": [],
            "read_evidence_ids": [],
            "read_files": [],
        }

        def model_result(system_prompt, messages, schema, name="structured_response", temperature=0.2):
            del system_prompt, messages, schema, temperature
            if name == "support_luna_validation":
                return {
                    "supported": True,
                    "answers_question": True,
                    "wrong_product_or_feature": False,
                    "incorrect_arithmetic": False,
                    "unnecessary_clarification": False,
                    "unsupported_claims": [],
                    "forbidden_claims": [],
                }
            self.assertEqual("support_luna_final", name)
            answer = (
                "The lead wallet transaction is processed first. Valhalla then "
                "queues the copying wallet's position from that observed event."
            )
            return {
                "action": "answer",
                "evidence_ids": [source["id"]],
                "claim_evidence": [{"claim": answer, "evidence_ids": [source["id"]]}],
                "missing_information": [],
                "draft_answer": answer,
            }

        mocked_ask.side_effect = model_result

        def agent_result(system_prompt, messages, schema, tools, executor, **kwargs):
            del system_prompt, messages, schema, tools, kwargs
            facts_result = executor("search_approved_facts", {
                "product": "valhalla", "query": question, "intent": "unknown",
            })
            self.assertEqual([], facts_result["results"])
            tool_result = executor("search_repository", {
                "product": "valhalla", "query": question, "limit": 8,
            })
            self.assertTrue(tool_result["results"])
            executor("read_repository_section", {
                "product": "valhalla", "path": source["path"], "line": source["line"],
            })
            answer = (
                "The lead wallet transaction is processed first. Valhalla then "
                "queues the copying wallet's position from that observed event."
            )
            return {
                "action": "answer", "evidence_ids": [source["id"]],
                "claim_evidence": [{"claim": answer, "evidence_ids": [source["id"]]}],
                "missing_information": [], "draft_answer": answer,
            }

        mocked_agent.side_effect = agent_result
        turns = [
            {"role": "user", "content": "Billi: older question {}".format(index)}
            for index in range(5)
        ] + [{"role": "user", "content": "Billi: " + question}]

        result = autonomous_decision(question, turns, force_reply=True)

        self.assertEqual("answer", result["action"])
        self.assertIn("processed first", result["draft_answer"])
        self.assertNotIn("close that position", result["draft_answer"])
        self.assertEqual(1, mocked_agent.call_count)


if __name__ == "__main__":
    unittest.main()
