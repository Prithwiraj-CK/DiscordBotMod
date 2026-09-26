"""Fixture-only regression tests for Olympus repository anchor ranking."""

import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from codebase_search import search_codebase


class CodebaseSearchRankingTests(unittest.TestCase):
    def _fixture_repository(self, root):
        files = {
            "docs/copy-settings.md": """# Copy settings

## Max Trade Size

**Max Trade Size** caps the amount allocated to one copied trade.
""",
            "src/max-trade-size.ts": """export function maxTradeSizeForLeader(value: number) {
  // Max Trade Size is applied before a copied order is submitted.
  return value;
}
""",
            # Filename-only discovery must not turn an empty placeholder into
            # an unreadable repository-tool anchor.
            "src/max-trade-size-placeholder.ts": "",
            "src/max-market-size.ts": """export function maxMarketSize(value: number) {
  return value;
}
""",
            "docs/loose-market-size.md": """# General copy discussion

This document mentions market activity and position size on separate concepts.
""",
            "src/transaction-byte-size.ts": """export function transactionTradeSize(bytes: Uint8Array) {
  // A transaction byte-size helper, unrelated to copy settings.
  return bytes.byteLength;
}
""",
            "reviews/trade-size-review.md": """# Review

This review discusses trade size in general terms only.
""",
            "src/loose-cooccurrence.ts": """export function trade(value: number) {
  const size = value;
  return size;
}
""",
            "src/polymarket-user-pnl.ts": """export interface PnlHistoryPoint {
  t: number;
  p: number;
}

export async function fetchPnlHistory(walletAddress: string) {
  return fetch(`/user-pnl?user_address=${walletAddress}`);
}
""",
            "src/WalletPnlChart.tsx": """export function WalletPnlChart({ data }: { data: PnlHistoryPoint[] }) {
  return <Chart data={data} />;
}
""",
            "docs/backtesting-audit.md": """# Audit notes

This discusses an unrelated historical equity curve and unrealized PnL.
""",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def _search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture_repository(root)
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                return search_codebase("What does Max Trade Size mean?", "olympus", limit=8)

    def test_exact_ui_label_docs_and_code_rank_before_generic_matches(self):
        anchors = self._search()
        paths = [anchor["path"] for anchor in anchors]
        self.assertIn("docs/copy-settings.md", paths)
        self.assertIn("src/max-trade-size.ts", paths)
        self.assertNotIn("reviews/trade-size-review.md", paths)
        self.assertGreater(anchors[0]["score_fields"]["exact_phrase"], 0)
        self.assertGreater(anchors[0]["score_fields"]["ui_label"], 0)
        self.assertTrue(all(count <= 2 for count in Counter(paths).values()))

    def test_generic_trade_size_and_transaction_byte_code_do_not_outrank_exact_label(self):
        anchors = self._search()
        paths = [anchor["path"] for anchor in anchors]
        self.assertNotIn("src/transaction-byte-size.ts", paths)
        self.assertNotIn("src/loose-cooccurrence.ts", paths)
        exact_scores = [
            anchor["score"] for anchor in anchors
            if anchor["path"] in {"docs/copy-settings.md", "src/max-trade-size.ts"}
        ]
        self.assertTrue(exact_scores)

    def test_empty_structural_filename_match_is_skipped_without_crashing(self):
        anchors = self._search()
        self.assertNotIn("src/max-trade-size-placeholder.ts", [anchor["path"] for anchor in anchors])

    def test_filename_or_symbol_exact_match_beats_loose_cooccurrence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture_repository(root)
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                anchors = search_codebase("What does Max Market Size mean?", "olympus", limit=8)
        self.assertEqual("src/max-market-size.ts", anchors[0]["path"])
        exact = anchors[0]
        self.assertGreater(exact["score_fields"]["filename"], 0)
        self.assertGreater(exact["score_fields"]["symbol"], 0)
        self.assertGreater(exact["score_fields"]["exact_phrase"], 0)

    def test_search_anchors_are_non_citable_and_expose_all_score_fields(self):
        anchors = self._search()
        expected = {
            "exact_phrase", "ui_label", "filename", "workflow_alias", "heading", "symbol", "route",
            "documentation", "executable_code", "test", "generated_or_plan_penalty", "token_overlap",
        }
        self.assertTrue(anchors)
        for anchor in anchors:
            self.assertFalse(anchor["citable"])
            self.assertEqual(expected, set(anchor["score_fields"]))

    def test_value_over_time_wording_finds_the_wallet_pnl_data_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture_repository(root)
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                anchors = search_codebase(
                    "Does the wallet value-over-time graph include unrealized profit and loss?",
                    "olympus",
                    limit=8,
                )
        paths = [anchor["path"] for anchor in anchors]
        self.assertIn("src/polymarket-user-pnl.ts", paths)
        self.assertIn("src/WalletPnlChart.tsx", paths)
        self.assertLess(
            paths.index("src/polymarket-user-pnl.ts"),
            paths.index("docs/backtesting-audit.md"),
        )
        self.assertTrue(all(anchor["citable"] is False for anchor in anchors))


if __name__ == "__main__":
    unittest.main()
