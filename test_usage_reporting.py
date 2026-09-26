import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import usage_reporting


class _Details:
    cached_tokens = 250
    cache_write_tokens = 50


class _OutputDetails:
    reasoning_tokens = 400


class _Usage:
    input_tokens = 1000
    output_tokens = 600
    input_tokens_details = _Details()
    output_tokens_details = _OutputDetails()


class UsageReportingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.ledger = root / "usage.jsonl"
        self.state = root / "state.json"
        self.environ = patch.dict(os.environ, {
            "USAGE_LEDGER_PATH": str(self.ledger),
            "USAGE_REPORT_STATE_PATH": str(self.state),
            "DAILY_USAGE_WEBHOOK_URL": "https://example.test/webhook",
            "USAGE_REPORT_LIVE_UPDATES": "false",
        }, clear=False)
        self.environ.start()

    def tearDown(self):
        self.environ.stop()
        self.directory.cleanup()

    def test_records_only_usage_and_calculates_luna_cost(self):
        usage_reporting.record_usage("gpt-6-luna", _Usage(), now=100)
        event = json.loads(self.ledger.read_text().strip())
        self.assertEqual(event["input_tokens"], 1000)
        self.assertEqual(event["cached_input_tokens"], 250)
        self.assertEqual(event["cache_write_tokens"], 50)
        self.assertEqual(event["output_tokens"], 600)
        self.assertEqual(event["reasoning_tokens"], 400)
        # 700 uncached input, 250 cached input, 50 cache-write, 600 output.
        self.assertAlmostEqual(event["estimated_cost_usd"], 0.00037875)
        self.assertNotIn("prompt", event)
        self.assertNotIn("output", event)

    @patch("usage_reporting.requests.post")
    def test_posts_the_completed_turn_and_cumulative_total(self, post):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"id": "usage-message"}
        with usage_reporting.support_turn_scope("turn-one"):
            usage_reporting.record_usage("gpt-6-luna", _Usage(), now=102)
        with usage_reporting.support_turn_scope("turn-two"):
            usage_reporting.record_usage("gpt-6-luna", _Usage(), now=103)

        self.assertTrue(usage_reporting.send_turn_snapshot("turn-two"))
        content = post.call_args.kwargs["json"]["content"]
        self.assertIn("This response estimated cost: **$0.000379**", content)
        self.assertIn("Bot total since local tracking began", content)
        self.assertIn("Total estimated cost: **$0.000758**", content)
        self.assertIn("Read: 1,000 input tokens", content)
        self.assertIn("Wrote: 600 output tokens (400 reasoning)", content)
        self.assertNotIn("Window:", content)
        self.assertEqual(1, post.call_count)

    def test_turn_scopes_keep_usage_separate(self):
        with usage_reporting.support_turn_scope("turn-one"):
            usage_reporting.record_usage("gpt-6-luna", _Usage(), now=102)
            usage_reporting.record_usage("gpt-6-luna", _Usage(), now=103)
        with usage_reporting.support_turn_scope("turn-two"):
            usage_reporting.record_usage("gpt-6-luna", _Usage(), now=104)

        first = usage_reporting.summarize_usage(turn_id="turn-one")
        second = usage_reporting.summarize_usage(turn_id="turn-two")
        self.assertEqual(2, first["calls"])
        self.assertEqual(1, second["calls"])
        self.assertEqual(2_000, first["input_tokens"])
        self.assertEqual(1_000, second["input_tokens"])

    def test_agents_session_usage_is_reported_with_the_turn(self):
        with usage_reporting.support_turn_scope("agent-turn"):
            usage_reporting.record_usage("gpt-6-astra", _Usage(), now=105, runtime="agents")

        totals = usage_reporting.summarize_usage(turn_id="agent-turn")
        self.assertEqual(1, totals["calls"])
        self.assertEqual(1, totals["agent_sessions"])
        self.assertEqual(0, totals["responses_calls"])
        self.assertEqual(1_000, totals["input_tokens"])
        self.assertEqual(600, totals["output_tokens"])
        self.assertEqual(1, totals["unknown_cost_calls"])
        self.assertIn("Agents sessions: 1 · Responses calls: 0", usage_reporting._format_totals(totals, "This response"))


if __name__ == "__main__":
    unittest.main()
