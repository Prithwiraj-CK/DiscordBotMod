import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import llm


class LlmTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
