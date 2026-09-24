import unittest
from unittest.mock import patch

from bot import (
    _discord_messages, _discord_post_message, _resolve_follow_up_question,
    _transport_mode,
)


class TransportModeTests(unittest.TestCase):
    def test_rest_is_default_and_invalid_values_fail_closed_to_rest(self):
        self.assertEqual("rest", _transport_mode(""))
        self.assertEqual("rest", _transport_mode("unexpected"))

    def test_gateway_requires_explicit_opt_in(self):
        self.assertEqual("gateway", _transport_mode("gateway"))
        self.assertEqual("rest", _transport_mode("REST"))

    @patch("bot.requests.get")
    def test_history_uses_native_rest_with_a_timeout(self, get):
        _discord_messages("123", 8, before="456")
        self.assertEqual(
            "https://discord.com/api/v9/channels/123/messages",
            get.call_args.args[0],
        )
        self.assertEqual({"limit": 8, "before": "456"}, get.call_args.kwargs["params"])
        self.assertEqual(20, get.call_args.kwargs["timeout"])

    @patch("bot.requests.post")
    def test_post_uses_native_rest_with_a_timeout(self, post):
        _discord_post_message("123", "hello", allowed_mentions={"parse": []})
        self.assertEqual(
            "https://discord.com/api/v9/channels/123/messages",
            post.call_args.args[0],
        )
        self.assertEqual("hello", post.call_args.kwargs["json"]["content"])
        self.assertEqual(20, post.call_args.kwargs["timeout"])

    def test_product_correction_reuses_the_parent_user_question(self):
        resolved = _resolve_follow_up_question(
            "i was asking about valhalla ratio",
            [
                {"role": "user", "content": "Billi: @Salena What does Ratio % do when copying a wallet?"},
                {"role": "assistant", "content": "Ratio % is an Olympus setting."},
            ],
        )
        self.assertIn("What does Ratio % do when copying a wallet?", resolved)
        self.assertIn("i was asking about valhalla ratio", resolved)


if __name__ == "__main__":
    unittest.main()
