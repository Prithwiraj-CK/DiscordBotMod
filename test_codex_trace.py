import os
import unittest
from unittest.mock import patch

from codex_trace import emit


class CodexTraceTests(unittest.TestCase):
    def test_only_discord_webhooks_receive_compact_safe_metadata(self):
        posted = []

        class Thread:
            def __init__(self, target, args, **_kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with patch.dict(os.environ, {
            "CODEX_TRACE_WEBHOOK_URL": "https://discord.com/api/webhooks/1/test",
        }, clear=False), patch("codex_trace.threading.Thread", Thread), \
                patch("codex_trace.requests.post", side_effect=lambda *args, **kwargs: posted.append((args, kwargs))):
            emit("snapshot_constructed", source_text="must not be sent", selected_files=12)

        self.assertEqual(1, len(posted))
        content = posted[0][1]["json"]["content"]
        self.assertIn("Olympus workspace prepared", content)
        self.assertIn("12 approved files", content)
        self.assertNotIn("must not be sent", content)
        self.assertNotIn("source_text", content)

    def test_invalid_webhook_destination_is_not_called(self):
        with patch.dict(os.environ, {
            "CODEX_TRACE_WEBHOOK_URL": "https://example.com/api/webhooks/1/test",
        }, clear=False), patch("codex_trace.requests.post") as post:
            emit("session_created")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
