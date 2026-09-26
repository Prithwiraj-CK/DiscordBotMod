import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import llm
import openai


class LlmTests(unittest.TestCase):
    def setUp(self):
        # llm.ask_json/ask_json_with_tools call llm.record_usage internally
        # on every real response, mocked SDK client or not. Unmocked, this
        # suite silently wrote a `usage_known:false, 0 tokens` entry to the
        # developer's real .runtime/openai_usage.jsonl on every test run,
        # inflating the real "Bot total since local tracking began" report
        # with test-run noise instead of real Discord activity.
        self._record_usage = patch("llm.record_usage")
        self._record_usage.start()

    def tearDown(self):
        self._record_usage.stop()

    def test_ask_json_retries_incomplete_response_and_uses_configured_budget(self):
        responses = Mock()
        responses.create.side_effect = [
            SimpleNamespace(output_text='{"answer":"partial', usage=None),
            SimpleNamespace(output_text='{"answer":"complete"}', usage=None),
        ]
        client = SimpleNamespace(responses=responses)
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }

        with patch.dict(os.environ, {
            "LLM_MAX_ATTEMPTS": "2",
            "LLM_JSON_MAX_OUTPUT_TOKENS": "1200",
        }, clear=False), patch("llm._get_client", return_value=client), patch("llm.time.sleep"):
            value = llm.ask_json("Return JSON.", [{"role": "user", "content": "hello"}], schema)

        self.assertEqual({"answer": "complete"}, value)
        self.assertEqual(2, responses.create.call_count)
        self.assertEqual(1200, responses.create.call_args.kwargs["max_output_tokens"])

    def test_tool_loop_preserves_response_output_before_compact_final_draft(self):
        tool_call = SimpleNamespace(
            type="function_call", name="search_repository", call_id="call_1",
            arguments='{"product":"olympus","query":"wallet roles","limit":4}',
        )
        first = SimpleNamespace(output=[SimpleNamespace(type="reasoning"), tool_call], output_text="", usage=None)
        second = SimpleNamespace(output=[], output_text='{"answer":"done"}', usage=None)
        responses = Mock()
        responses.create.side_effect = [first, second]
        client = SimpleNamespace(responses=responses)
        schema = {
            "type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"], "additionalProperties": False,
        }
        seen = []
        with patch("llm._get_client", return_value=client):
            with self.assertRaisesRegex(llm.ResearchLoopFinished, "complete"):
                llm.ask_json_with_tools(
                    "research", [{"role": "user", "content": "question"}], schema,
                    [{"type": "function", "name": "search_repository", "parameters": {"type": "object"}}],
                    lambda name, arguments: seen.append((name, arguments)) or {"results": []},
                    require_initial_tool=True,
                )

        self.assertEqual([("search_repository", {"product": "olympus", "query": "wallet roles", "limit": 4})], seen)
        second_input = responses.create.call_args_list[1].kwargs["input"]
        self.assertIn(tool_call, second_input)
        self.assertTrue(any(item.get("type") == "function_call_output" for item in second_input if isinstance(item, dict)))

    def test_tool_loop_reports_its_tool_budget_without_raw_final_draft(self):
        first_call = SimpleNamespace(type="function_call", name="search_repository", call_id="call_1", arguments="{}")
        responses = Mock()
        responses.create.side_effect = [
            SimpleNamespace(output=[first_call], output_text="", usage=None),
            SimpleNamespace(output=[], output_text='{"answer":"researched"}', usage=None),
        ]
        client = SimpleNamespace(responses=responses)
        schema = {
            "type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"], "additionalProperties": False,
        }
        with patch("llm._get_client", return_value=client):
            with self.assertRaisesRegex(llm.ResearchLoopFinished, "tool_budget"):
                llm.ask_json_with_tools(
                    "research", [{"role": "user", "content": "question"}], schema,
                    [{"type": "function", "name": "search_repository", "parameters": {"type": "object"}}],
                    lambda name, arguments: {"results": []}, max_tool_rounds=1,
                )

        self.assertEqual(1, responses.create.call_count)

    def test_transient_transport_retry_does_not_consume_research_round(self):
        call = SimpleNamespace(type="function_call", name="search_repository", call_id="call_1", arguments="{}")
        responses = Mock()
        responses.create.side_effect = [
            openai.APIConnectionError(request=Mock()),
            SimpleNamespace(output=[call], output_text="", usage=None),
        ]
        client = SimpleNamespace(responses=responses)
        schema = {
            "type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"], "additionalProperties": False,
        }
        with patch.dict(os.environ, {"LLM_MAX_ATTEMPTS": "2"}, clear=False), \
             patch("llm._get_client", return_value=client), patch("llm.time.sleep"):
            with self.assertRaisesRegex(llm.ResearchLoopFinished, "tool_budget"):
                llm.ask_json_with_tools(
                    "research", [{"role": "user", "content": "question"}], schema,
                    [{"type": "function", "name": "search_repository", "parameters": {"type": "object"}}],
                    lambda _name, _arguments: {"results": []}, max_tool_rounds=1,
                )
        self.assertEqual(2, responses.create.call_count)


if __name__ == "__main__":
    unittest.main()
