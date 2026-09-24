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

    @patch("usage_reporting.requests.patch")
    @patch("usage_reporting.requests.post")
    def test_creates_then_updates_one_report_message(self, post, patch_request):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"id": "usage-message"}
        patch_request.return_value.raise_for_status.return_value = None
        usage_reporting.record_usage("gpt-6-luna", _Usage(), now=102)
        self.assertTrue(usage_reporting.send_due_report(now=100 + 86400))
        self.assertTrue(usage_reporting.update_current_report(now=100 + 86401))
        self.assertFalse(usage_reporting.send_due_report(now=100 + 86401))
        content = post.call_args.kwargs["json"]["content"]
        self.assertIn("Estimated cost: **$0.000379**", content)
        self.assertIn("Read: 1,000 input tokens", content)
        self.assertIn("Wrote: 600 output tokens (400 reasoning)", content)
        self.assertIn("/messages/usage-message", patch_request.call_args.args[0])
        self.assertIn("Calls: 1", patch_request.call_args.kwargs["json"]["content"])


if __name__ == "__main__":
    unittest.main()
