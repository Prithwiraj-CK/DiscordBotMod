"""Offline regression coverage for the live Olympus-only support boundary."""

import unittest
from unittest.mock import patch

from bot import (
    ESCALATE,
    LUNA_RESEARCH_TOOLS,
    UNSUPPORTED_PRODUCT_HANDOFF,
    autonomous_decision,
)


OLYMPUS_FACT = {
    "id": "olympus.scope.fact",
    "product": "olympus",
    "source_type": "approved_fact",
    "source": "approved_facts.json",
    "fact": "Olympus support fact.",
}
OLYMPUS_SEARCH = {
    "id": "codebase.olympus.scope.anchor",
    "product": "olympus",
    "source_type": "codebase",
    "source": "wallet.ts:20",
    "path": "wallet.ts",
    "line": 20,
    "fact": "Olympus repository search anchor.",
}
OLYMPUS_SECTION = {
    "id": "codebase.olympus.scope.section",
    "product": "olympus",
    "source_type": "codebase_section",
    "source": "wallet.ts:10-40",
    "path": "wallet.ts",
    "line": 20,
    "fact": "Olympus complete repository section.",
}


class OlympusScopeTests(unittest.TestCase):
    def _grounded_agent(self, observed_products):
        def agent(_system, _messages, _schema, _tools, executor, **_kwargs):
            facts = executor("search_approved_facts", {
                "product": "olympus", "query": "question", "intent": "unknown",
            })
            observed_products.append("olympus")
            self.assertEqual([OLYMPUS_FACT["id"]], [item["id"] for item in facts["results"]])
            hits = executor("search_repository", {
                "product": "olympus", "query": "question", "limit": 8,
            })
            observed_products.append("olympus")
            self.assertEqual([OLYMPUS_SEARCH["id"]], [item["id"] for item in hits["results"]])
            section = executor("read_repository_section", {
                "product": "olympus", "path": "wallet.ts", "line": 20,
            })
            observed_products.append("olympus")
            self.assertEqual(OLYMPUS_SECTION["id"], section["result"]["id"])
            answer = "Olympus support answer."
            return {
                "action": "answer",
                "evidence_ids": [OLYMPUS_SECTION["id"]],
                "claim_evidence": [{
                    "claim": answer, "evidence_ids": [OLYMPUS_SECTION["id"]],
                }],
                "missing_information": [],
                "draft_answer": answer,
                "coverage": {
                    "complete": True,
                    "uncovered_parts": [],
                    "part_evidence": [{
                        "part": "the user's Olympus support question",
                        "evidence_ids": [OLYMPUS_SECTION["id"]],
                    }],
                },
            }
        return agent

    def _run_grounded_question(self, question):
        observed_products = []
        with patch("bot.retrieve_facts", return_value=[OLYMPUS_FACT]), \
             patch("bot.search_codebase", return_value=[OLYMPUS_SEARCH]), \
             patch("bot.read_codebase_section", return_value=OLYMPUS_SECTION), \
             patch("bot.ask_json_with_tools", side_effect=self._grounded_agent(observed_products)):
            result = autonomous_decision(question, [{"role": "user", "content": question}])
        return result, observed_products

    def test_olympus_question_searches_only_olympus(self):
        result, products = self._run_grounded_question("In Olympus, what does Ratio % do?")
        self.assertEqual("answer", result["action"])
        self.assertEqual(["olympus", "olympus", "olympus"], products)
        self.assertTrue(all("valhalla" not in item for item in result["evidence_ids"]))

    def test_shared_label_defaults_to_olympus_research(self):
        result, products = self._run_grounded_question("What does Max Trade Size do when copying a wallet?")
        self.assertEqual("olympus", result["product"])
        self.assertEqual(["olympus", "olympus", "olympus"], products)

    def test_explicit_valhalla_never_calls_model_or_research(self):
        with patch("bot.ask_json_with_tools") as model, \
             patch("bot.retrieve_facts") as facts, \
             patch("bot.search_codebase") as search, \
             patch("bot.read_codebase_section") as section, \
             patch("bot.read_codebase_file") as file_reader:
            result = autonomous_decision(
                "In Valhalla, what does Ratio % do?",
                [{"role": "user", "content": "In Valhalla, what does Ratio % do?"}],
            )
        self.assertEqual("escalate", result["action"])
        self.assertEqual(UNSUPPORTED_PRODUCT_HANDOFF, result["draft_answer"])
        model.assert_not_called()
        facts.assert_not_called()
        search.assert_not_called()
        section.assert_not_called()
        file_reader.assert_not_called()

    def test_valhalla_fact_is_excluded_from_an_olympus_evidence_packet(self):
        valhalla_fact = dict(OLYMPUS_FACT, id="valhalla.scope.fact", product="valhalla")
        observed_products = []
        with patch("bot.retrieve_facts", return_value=[OLYMPUS_FACT, valhalla_fact]), \
             patch("bot.search_codebase", return_value=[OLYMPUS_SEARCH]), \
             patch("bot.read_codebase_section", return_value=OLYMPUS_SECTION), \
             patch("bot.ask_json_with_tools", side_effect=self._grounded_agent(observed_products)):
            result = autonomous_decision("In Olympus, what does Ratio % do?", [])
        self.assertEqual(["olympus", "olympus", "olympus"], observed_products)
        self.assertNotIn("valhalla.scope.fact", result["evidence_ids"])

    def test_account_and_security_escalation_still_wins(self):
        with patch("bot.ask_json_with_tools") as model:
            result = autonomous_decision("My Olympus wallet may be compromised; can you check it?", [])
        self.assertEqual("escalate", result["action"])
        self.assertEqual(ESCALATE, result["draft_answer"])
        model.assert_not_called()

    def test_social_reply_and_live_tool_scope_remain_available(self):
        result = autonomous_decision("hi", [], force_reply=True)
        self.assertEqual("answer", result["action"])
        self.assertEqual("social", result["intent"])
        enums = [tool["parameters"]["properties"]["product"]["enum"] for tool in LUNA_RESEARCH_TOOLS]
        self.assertEqual([["olympus"]] * len(enums), enums)


if __name__ == "__main__":
    unittest.main()
