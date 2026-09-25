"""Offline regression tests for the bounded adaptive Olympus research loop."""

import unittest
from unittest.mock import patch

import llm
from bot import autonomous_decision


def plan(*subquestions):
    return {
        "normalized_question": "Olympus question",
        "subquestions": [
            {"subquestion": value, "needed": "current Olympus behavior"}
            for value in subquestions
        ],
    }


def draft(subquestions, evidence_ids, *, complete=True):
    return {
        "action": "answer", "evidence_ids": list(evidence_ids),
        "claim_evidence": [{"claim": "Grounded Olympus answer.", "evidence_ids": list(evidence_ids)}],
        "missing_information": [], "draft_answer": "Grounded Olympus answer.",
        "coverage": {
            "complete": complete,
            "uncovered_parts": [] if complete else [subquestions[-1]],
            "part_evidence": [
                {"part": value, "evidence_ids": list(evidence_ids)}
                for value in subquestions if complete
            ],
        },
        "coverage_ledger": [
            {
                "subquestion": value,
                "status": "covered" if complete or index == 0 else "missing",
                "supporting_evidence_ids": list(evidence_ids) if complete or index == 0 else [],
                "conflicts": [],
                "missing_items": [] if complete or index == 0 else [value],
            }
            for index, value in enumerate(subquestions)
        ],
    }


class AdaptiveResearchLoopTests(unittest.TestCase):
    def _run(self, question, research, plan_value, final_value, tool_results, budget=None):
        calls = []

        class RepoTools:
            def __init__(self, received_budget):
                self.budget = received_budget

            def execute(self, name, arguments):
                calls.append((name, dict(arguments)))
                self.budget.reserve_tool_call(name)
                result = tool_results.get((name, arguments.get("query") or arguments.get("anchor_id")), {
                    "anchors": [],
                })
                self.budget.record_tool_output(result)
                return result

        def writer(_system, _messages, _schema, name="", **_kwargs):
            if name == "support_luna_research_plan":
                return plan_value
            return final_value

        patches = [
            patch("bot.OlympusRepositoryTools", RepoTools),
            patch("bot.ask_json", side_effect=writer),
            patch("bot.ask_json_with_tools", side_effect=research),
        ]
        if budget is not None:
            patches.append(patch("bot.ResearchBudget.from_environment", return_value=budget))
        with patches[0], patches[1], patches[2]:
            if len(patches) == 4:
                with patches[3]:
                    result = autonomous_decision(question, [])
            else:
                result = autonomous_decision(question, [])
        return result, calls

    def test_weak_first_search_is_reformulated(self):
        source = {
            "id": "repo.wallet.roles", "source_type": "codebase_section",
            "fact": "Complete Olympus wallet roles section.", "citable": True,
        }

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_repository", {"query": "wallet", "limit": 4})
            anchors = executor("search_repository", {"query": "signing trading deposit addresses", "limit": 4})
            executor("read_section", {"anchor_id": anchors["anchors"][0]["anchor_id"]})
            raise llm.ResearchLoopFinished("complete")

        result, calls = self._run(
            "Why does a new Olympus wallet have signing, trading, and deposit addresses?",
            research, plan("wallet address roles"), draft(["wallet address roles"], [source["id"]]),
            {
                ("search_repository", "wallet"): {"anchors": []},
                ("search_repository", "signing trading deposit addresses"): {
                    "anchors": [{"anchor_id": "oa_roles", "citable": False}],
                },
                ("read_section", "oa_roles"): {"evidence": source},
            },
        )
        self.assertEqual("answer", result["action"])
        self.assertEqual(
            ["wallet", "signing trading deposit addresses"],
            [arguments.get("query") for name, arguments in calls if name == "search_repository"],
        )

    def test_loop_can_follow_symbol_to_callers_and_tests(self):
        caller = {"id": "repo.caller", "source_type": "codebase_section", "fact": "Caller section.", "citable": True}
        test = {"id": "repo.test", "source_type": "codebase_section", "fact": "Test section.", "citable": True}

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            symbols = executor("search_symbols", {"query": "createWallet", "limit": 4})
            executor("read_callers", {"anchor_id": symbols["anchors"][0]["anchor_id"], "limit": 2})
            executor("read_tests_for_symbol", {"anchor_id": symbols["anchors"][0]["anchor_id"], "limit": 2})
            raise llm.ResearchLoopFinished("complete")

        result, calls = self._run(
            "What happens when Olympus creates a wallet?", research,
            plan("wallet creation behavior"), draft(["wallet creation behavior"], [caller["id"], test["id"]]),
            {
                ("search_symbols", "createWallet"): {"anchors": [{"anchor_id": "oa_create", "citable": False}]},
                ("read_callers", "oa_create"): {"sections": [caller]},
                ("read_tests_for_symbol", "oa_create"): {"sections": [test]},
            },
        )
        self.assertEqual("answer", result["action"])
        self.assertEqual(
            ["search_symbols", "read_callers", "read_tests_for_symbol"], [name for name, _ in calls],
        )

    def test_compound_question_requires_each_planned_part(self):
        source = {"id": "repo.one", "source_type": "codebase_section", "fact": "One complete section.", "citable": True}

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            anchors = executor("search_repository", {"query": "wallet roles", "limit": 4})
            executor("read_section", {"anchor_id": anchors["anchors"][0]["anchor_id"]})
            raise llm.ResearchLoopFinished("complete")

        result, _ = self._run(
            "Why are the addresses separate and which one can receive deposits?", research,
            plan("why addresses are separate", "which address receives deposits"),
            draft(["why addresses are separate", "which address receives deposits"], [source["id"]], complete=False),
            {
                ("search_repository", "wallet roles"): {"anchors": [{"anchor_id": "oa_roles", "citable": False}]},
                ("read_section", "oa_roles"): {"evidence": source},
            },
        )
        self.assertEqual("escalate", result["action"])

    def test_duplicate_operation_terminates_without_guessing(self):
        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_repository", {"query": "wallet roles", "limit": 4})
            duplicate = executor("search_repository", {"query": "wallet roles", "limit": 4})
            self.assertEqual("no_progress", duplicate["_stop_reason"])
            raise llm.ResearchLoopFinished("no_progress")

        result, _ = self._run(
            "What are Olympus wallet roles?", research, plan("wallet roles"),
            draft(["wallet roles"], ["unused"]), {("search_repository", "wallet roles"): {"anchors": []}},
        )
        self.assertEqual("escalate", result["action"])

    def test_two_no_progress_operations_terminate_safely(self):
        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_repository", {"query": "wallet roles", "limit": 4})
            empty = executor("search_symbols", {"query": "missingSymbol", "limit": 4})
            self.assertEqual("no_progress", empty["_stop_reason"])
            raise llm.ResearchLoopFinished("no_progress")

        result, _ = self._run(
            "What are Olympus wallet roles?", research, plan("wallet roles"),
            draft(["wallet roles"], ["unused"]), {
                ("search_repository", "wallet roles"): {"anchors": []},
                ("search_symbols", "missingSymbol"): {"anchors": []},
            },
        )
        self.assertEqual("escalate", result["action"])

    def test_anchor_only_research_cannot_produce_answer(self):
        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_repository", {"query": "wallet roles", "limit": 4})
            raise llm.ResearchLoopFinished("complete")

        result, _ = self._run(
            "What are Olympus wallet roles?", research, plan("wallet roles"),
            draft(["wallet roles"], ["anchor"]),
            {("search_repository", "wallet roles"): {"anchors": [{"anchor_id": "oa_roles", "citable": False}]}},
        )
        self.assertEqual("escalate", result["action"])

    def test_complete_evidence_stops_before_full_tool_budget(self):
        source = {"id": "repo.complete", "source_type": "codebase_section", "fact": "Complete section.", "citable": True}
        budget = llm.ResearchBudget(max_tool_calls=10)

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            anchors = executor("search_repository", {"query": "wallet roles", "limit": 4})
            executor("read_section", {"anchor_id": anchors["anchors"][0]["anchor_id"]})
            raise llm.ResearchLoopFinished("complete")

        result, calls = self._run(
            "What are Olympus wallet roles?", research, plan("wallet roles"),
            draft(["wallet roles"], [source["id"]]),
            {
                ("search_repository", "wallet roles"): {"anchors": [{"anchor_id": "oa_roles", "citable": False}]},
                ("read_section", "oa_roles"): {"evidence": source},
            }, budget=budget,
        )
        self.assertEqual("answer", result["action"])
        self.assertLess(len(calls), budget.max_tool_calls)

    def test_budget_exhaustion_abstains_without_a_guessed_answer(self):
        budget = llm.ResearchBudget(max_tool_calls=1)

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_repository", {"query": "wallet roles", "limit": 4})
            executor("search_symbols", {"query": "createWallet", "limit": 4})
            raise AssertionError("second tool should exhaust the budget")

        result, _ = self._run(
            "What are Olympus wallet roles?", research, plan("wallet roles"),
            draft(["wallet roles"], ["unused"]),
            {("search_repository", "wallet roles"): {"anchors": []}}, budget=budget,
        )
        self.assertEqual("escalate", result["action"])
        self.assertIn("budget exhausted / evidence incomplete", result["missing_information"])


if __name__ == "__main__":
    unittest.main()
