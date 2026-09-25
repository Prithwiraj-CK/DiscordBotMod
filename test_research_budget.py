"""Offline regression coverage for per-support-turn research limits."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import llm
from bot import ESCALATE, autonomous_decision
from codebase_search import read_codebase_file


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _usage(input_tokens, output_tokens=0, cached_tokens=0, reasoning_tokens=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_tokens_details": {"cached_tokens": cached_tokens},
        "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
    }


class ResearchBudgetTests(unittest.TestCase):
    def test_repeated_tool_results_cannot_exceed_tool_output_budget(self):
        budget = llm.ResearchBudget(max_tool_output_tokens=20)
        payload = {"results": [{"id": "anchor", "preview": "brief"}]}
        with self.assertRaises(llm.ResearchBudgetExceeded):
            while True:
                budget.record_tool_output(payload)
        self.assertLessEqual(budget.tool_output_tokens, budget.max_tool_output_tokens)
        self.assertEqual("token_budget", budget.stop_reason)

    def test_cumulative_input_accounting_includes_every_model_call(self):
        responses = Mock()
        responses.create.side_effect = [
            SimpleNamespace(output_text='{"answer":"one"}', usage=_usage(125, 20, 10, 5)),
            SimpleNamespace(output_text='{"answer":"two"}', usage=_usage(175, 25, 15, 7)),
        ]
        client = SimpleNamespace(responses=responses)
        budget = llm.ResearchBudget(max_total_input_tokens=2_000)
        with patch("llm._get_client", return_value=client), patch("llm.record_usage"), llm.research_budget_scope(budget):
            self.assertEqual({"answer": "one"}, llm.ask_json("system", [{"role": "user", "content": "one"}], SCHEMA))
            self.assertEqual({"answer": "two"}, llm.ask_json("system", [{"role": "user", "content": "two"}], SCHEMA))
        self.assertEqual(2, budget.api_calls)
        self.assertEqual(300, budget.input_tokens)
        self.assertEqual(25, budget.cached_input_tokens)
        self.assertEqual(45, budget.output_tokens)
        self.assertEqual(12, budget.reasoning_tokens)

    def test_concurrent_turns_keep_budget_state_isolated(self):
        results = []
        lock = threading.Lock()

        def worker(tokens):
            budget = llm.ResearchBudget(max_total_input_tokens=1_000)
            with llm.research_budget_scope(budget):
                budget.before_model_call(30)
                budget.record_response(_usage(tokens), 30)
            with lock:
                results.append(budget.summary())

        threads = [threading.Thread(target=worker, args=(101,)), threading.Thread(target=worker, args=(202,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual({101, 202}, {result["input_tokens"] for result in results})
        self.assertTrue(all(result["api_calls"] == 1 for result in results))

    def test_context_budget_exhaustion_abstains_without_model_call(self):
        with patch.dict(os.environ, {"RESEARCH_MAX_CONTEXT_TOKENS": "1"}, clear=False), \
             patch("llm._get_client") as client:
            result = autonomous_decision("In Olympus, what does Ratio % do?", [])
        self.assertEqual("escalate", result["action"])
        self.assertEqual(ESCALATE, result["draft_answer"])
        self.assertIn("budget exhausted / evidence incomplete", result["missing_information"])
        client.assert_not_called()

    def test_codebase_file_read_is_limited_by_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workflow.py").write_text("\n".join(
                "value_{} = 'long repository line'".format(index)
                for index in range(100)
            ))
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                item = read_codebase_file("olympus", "workflow.py", 1, 100, max_tokens=40)
        self.assertIsNotNone(item)
        self.assertLessEqual(llm.estimate_tokens(item["fact"]), 40)

    def test_no_evidence_records_no_progress_and_hands_off(self):
        budget = llm.ResearchBudget()
        with patch("bot.ResearchBudget.from_environment", return_value=budget), \
             patch("bot.ask_json_with_tools", side_effect=llm.ResearchLoopFinished("complete")):
            result = autonomous_decision("In Olympus, what does Ratio % do?", [])
        self.assertEqual("escalate", result["action"])
        self.assertEqual("no_progress", budget.stop_reason)

    def test_final_writer_receives_only_selected_compact_evidence(self):
        fact = {
            "id": "olympus.fact", "product": "olympus", "source_type": "approved_fact",
            "fact": "Approved Olympus fact.",
        }
        anchor = {
            "id": "codebase.olympus.anchor", "product": "olympus", "source_type": "codebase",
            "path": "wallet.ts", "line": 20, "fact": "RAW SEARCH ANCHOR MUST NOT REACH FINAL WRITER",
        }
        section = {
            "id": "codebase.olympus.section", "product": "olympus", "source_type": "codebase_section",
            "path": "wallet.ts", "line": 20, "fact": "Selected complete section.",
        }
        final_prompts = []

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_approved_facts", {"product": "olympus", "query": "ratio", "intent": "unknown"})
            executor("search_repository", {"product": "olympus", "query": "ratio", "limit": 8})
            executor("read_repository_section", {"product": "olympus", "path": "wallet.ts", "line": 20})
            raise llm.ResearchLoopFinished("complete")

        def final_writer(system, *_args, **_kwargs):
            final_prompts.append(system)
            answer = "Selected compact answer."
            return {
                "action": "answer", "evidence_ids": [section["id"]],
                "claim_evidence": [{"claim": answer, "evidence_ids": [section["id"]]}],
                "missing_information": [], "draft_answer": answer,
                "coverage": {
                    "complete": True,
                    "uncovered_parts": [],
                    "part_evidence": [{"part": "Ratio % behavior", "evidence_ids": [section["id"]]}],
                },
            }

        with patch("bot.retrieve_facts", return_value=[fact]), \
             patch("bot.search_codebase", return_value=[anchor]), \
             patch("bot.read_codebase_section", return_value=section), \
             patch("bot.ask_json_with_tools", side_effect=research), \
             patch("bot.ask_json", side_effect=final_writer):
            result = autonomous_decision("In Olympus, what does Ratio % do?", [])
        self.assertEqual("answer", result["action"])
        self.assertEqual(1, len(final_prompts))
        self.assertIn("olympus.fact", final_prompts[0])
        self.assertIn("codebase.olympus.section", final_prompts[0])
        self.assertNotIn("RAW SEARCH ANCHOR", final_prompts[0])

    def test_incomplete_selected_evidence_hands_off_with_budget_remaining(self):
        section = {
            "id": "codebase.olympus.partial", "product": "olympus",
            "source_type": "codebase_section", "path": "wallet.ts", "line": 20,
            "fact": "The signing address authorizes wallet actions.",
        }

        def research(_system, _messages, _schema, _tools, executor, **_kwargs):
            executor("search_approved_facts", {
                "product": "olympus", "query": "wallet addresses", "intent": "wallets",
            })
            executor("search_repository", {
                "product": "olympus", "query": "wallet addresses", "limit": 8,
            })
            executor("read_repository_section", {
                "product": "olympus", "path": "wallet.ts", "line": 20,
            })
            return {
                "action": "answer", "evidence_ids": [section["id"]],
                "claim_evidence": [{
                    "claim": "The signing address authorizes actions.",
                    "evidence_ids": [section["id"]],
                }],
                "missing_information": [],
                "draft_answer": "The signing address authorizes actions.",
                "coverage": {
                    "complete": False,
                    "uncovered_parts": ["the distinct trading and deposit address roles"],
                    "part_evidence": [{
                        "part": "the signing address role",
                        "evidence_ids": [section["id"]],
                    }],
                },
            }

        budget = llm.ResearchBudget(max_total_input_tokens=50_000)
        with patch("bot.ResearchBudget.from_environment", return_value=budget), \
             patch("bot.retrieve_facts", return_value=[]), \
             patch("bot.search_codebase", return_value=[]), \
             patch("bot.read_codebase_section", return_value=section), \
             patch("bot.ask_json_with_tools", side_effect=research):
            result = autonomous_decision(
                "Why does a new Olympus wallet have signing, trading, and deposit addresses?", [],
            )
        self.assertEqual("escalate", result["action"])
        self.assertEqual("no_progress", budget.stop_reason)
        self.assertIn("the distinct trading and deposit address roles", result["missing_information"])
        self.assertGreater(budget.max_total_input_tokens - budget.input_tokens, 0)


if __name__ == "__main__":
    unittest.main()
