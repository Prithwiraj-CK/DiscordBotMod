import unittest
from datetime import datetime, timezone

from support_pipeline import (
    calculate, calculate_apr, calculate_fees_and_net, calculate_pnl,
    calculate_position_exposure, calculate_stop_take_prices, calculate_support_values, days_until, detect_product_feature,
    extract_question, format_calculation_response, rank_evidence,
)


COPY_SIZING_QUESTION = """If I am copying an address and the address can open 2 additional positions
within an active trade using 1 percent of AUM during each opening, and if the most I wish to spend per
active trade is $3, with $1 per position add, what number do I need to include in max trade and max market size?
Screenshot: Ratio % currently shows 1000. Max Trade Size shows 1. Max Market Size shows 3."""


class SupportPipelineTests(unittest.TestCase):
    def test_exact_olympus_labels_beat_generic_market_language(self):
        detected = detect_product_feature(COPY_SIZING_QUESTION)
        self.assertEqual("olympus", detected["product"])
        self.assertEqual("copy_trading", detected["feature"])
        self.assertIn("Max Trade Size", detected["exact_labels"])
        self.assertIn("Max Market Size", detected["exact_labels"])

    def test_copy_sizing_extracts_message_and_screenshot_values(self):
        record = extract_question(COPY_SIZING_QUESTION, detect_product_feature(COPY_SIZING_QUESTION))
        self.assertEqual(2, record["values"]["additional_entries"])
        self.assertEqual(1, record["values"]["amount_per_entry_usd"])
        self.assertEqual(3, record["values"]["maximum_total_usd"])
        self.assertEqual(1000, record["values"]["visible_ratio_field"])

    def test_copy_sizing_is_deterministic(self):
        record = extract_question(COPY_SIZING_QUESTION, detect_product_feature(COPY_SIZING_QUESTION))
        calculation = calculate_support_values(record)
        self.assertTrue(record["answerable"])
        self.assertEqual(1, calculation["max_trade_size_usd"])
        self.assertEqual(3, calculation["max_market_size_usd"])
        self.assertEqual(3, calculation["max_trades_per_market"])
        self.assertIn("enter 1", format_calculation_response(calculation))

    def test_valhalla_terms_choose_valhalla(self):
        detected = detect_product_feature("Where do I set the Jupiter Score filter for my DLMM follow?")
        self.assertEqual("valhalla", detected["product"])
        self.assertEqual("copy_trading", detected["feature"])

    def test_follow_up_uses_established_product_to_break_a_shared_label_tie(self):
        detected = detect_product_feature("What does Max Trade Size mean?", prior_product="olympus")
        self.assertEqual("olympus", detected["product"])
        self.assertIn("Max Trade Size", detected["exact_labels"])

    def test_generic_market_is_not_assumed_to_be_sports(self):
        detected = detect_product_feature("Which market is most active today?")
        self.assertEqual("unknown", detected["product"])

    def test_conflicting_screenshot_values_do_not_replace_user_values(self):
        question = "In Olympus, Max Trade Size shows 5, but I want $1 per entry and $3 total with 2 additional entries."
        record = extract_question(question, detect_product_feature(question))
        calculation = calculate_support_values(record)
        self.assertEqual(1, calculation["max_trade_size_usd"])
        self.assertEqual(3, calculation["max_market_size_usd"])
        self.assertEqual(5, record["values"]["visible_max_trade_size_usd"])

    def test_screenshot_only_labels_are_extracted(self):
        text = "OCR: Olympus settings — Ratio % 1000; Max Trade Size $1; Max Market Size $3."
        record = extract_question(text, detect_product_feature(text))
        self.assertEqual("olympus", record["product"])
        self.assertEqual(1000, record["values"]["visible_ratio_field"])
        self.assertEqual(1, record["values"]["visible_max_trade_size_usd"])
        self.assertEqual(3, record["values"]["visible_max_market_size_usd"])

    def test_truly_ambiguous_question_stays_unknown(self):
        detected = detect_product_feature("Why is this setting different?")
        self.assertEqual("unknown", detected["product"])
        self.assertEqual("unknown", detected["feature"])

    def test_insufficient_sizing_values_do_not_trigger_a_calculation(self):
        record = extract_question(
            "In Olympus copy trading, what should I set for Max Market Size?",
            detect_product_feature("In Olympus copy trading, what should I set for Max Market Size?"),
        )
        self.assertIsNone(calculate_support_values(record))
        self.assertFalse(record["answerable"])

    def test_reranker_prefers_exact_canonical_evidence(self):
        detection = detect_product_feature(COPY_SIZING_QUESTION)
        evidence = [
            {"id": "noise", "source_type": "history", "source": "general", "fact": "market trade"},
            {"id": "label", "source_type": "codebase_section", "source": "settings.ts", "fact": "Max Market Size maps to max_total_position_per_market."},
        ]
        self.assertEqual("label", rank_evidence(evidence, COPY_SIZING_QUESTION, detection)[0]["id"])

    def test_calculator_rejects_code(self):
        self.assertEqual(7, calculate("1 + 2 * 3"))
        with self.assertRaises(ValueError):
            calculate("__import__('os').system('false')")

    def test_reusable_financial_calculators(self):
        self.assertEqual(8, calculate_pnl(10, 14, 2)["gross_pnl"])
        self.assertEqual(3, calculate_fees_and_net(100, 3)["fee"])
        self.assertEqual(97, calculate_fees_and_net(100, 3)["net_amount"])
        self.assertEqual(365, calculate_apr(100, 10, 10))
        levels = calculate_stop_take_prices(100, 10, 25)
        self.assertEqual(90, levels["stop_loss_price"])
        self.assertEqual(125, levels["take_profit_price"])
        self.assertEqual(6, calculate_position_exposure([1, 2, 3]))
        self.assertEqual(1, days_until("2026-01-02T00:00:00Z", datetime(2026, 1, 1, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
