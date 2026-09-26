"""Regression coverage for the pinned wallet-discovery channel links.

A support operator asked that "how do I find a profitable wallet to
follow/copy" answers always include the staff-curated pinned-channel links,
for both Olympus and Valhalla. This is implemented entirely as approved-facts
data (knowledge/approved_facts.json) plus a retrieval-scoring boost
(knowledge.retrieve_facts), not a special-cased code path, so it goes through
the same evidence pipeline as every other approved fact.
"""

import unittest

import bot
from knowledge import retrieve_facts

OLYMPUS_LINKS = [
    "https://discord.com/channels/925207817923743794/1509446310552539267",
    "https://discord.com/channels/925207817923743794/1484775608922673314",
]
VALHALLA_LINK = "https://discord.com/channels/925207817923743794/1484774527610392576"

# The live tool-driven research loop calls retrieve_facts with limit=4
# (bot.py's search_approved_facts tool: limit=min(4, budget.remaining_evidence_items())).
# A fact that scores too low to survive that cutoff is effectively invisible
# to Luna, so every case here is checked at that real limit, not a looser one.
_LIVE_LIMIT = 4


class WalletDiscoveryLinkTests(unittest.TestCase):
    def test_olympus_plural_wallets_phrasing_surfaces_the_fact_with_links(self):
        # This exact phrasing ("find wallets to follow") previously missed
        # the relevance boost entirely: the regex required singular "wallet".
        facts = retrieve_facts(
            "How do I find wallets to follow in Olympus?",
            product="olympus", intent="copy_trading", limit=_LIVE_LIMIT,
        )
        ids = [fact["id"] for fact in facts]
        self.assertIn("olympus.copy_trade.wallet_discovery", ids)
        fact = next(f for f in facts if f["id"] == "olympus.copy_trade.wallet_discovery")
        self.assertEqual(OLYMPUS_LINKS, fact["links"])

    def test_valhalla_plural_wallets_phrasing_surfaces_the_fact_with_links(self):
        facts = retrieve_facts(
            "how do i find wallets to follow in valhalla",
            product="valhalla", intent="copy_trading", limit=_LIVE_LIMIT,
        )
        ids = [fact["id"] for fact in facts]
        self.assertIn("valhalla.copy_trade.wallet_discovery", ids)
        fact = next(f for f in facts if f["id"] == "valhalla.copy_trade.wallet_discovery")
        self.assertEqual([VALHALLA_LINK], fact["links"])

    def test_profitable_or_best_wallet_phrasing_also_surfaces_the_fact(self):
        for product, question, expected_id in (
            ("olympus", "what's a good wallet to copy", "olympus.copy_trade.wallet_discovery"),
            ("olympus", "which wallet is most profitable to follow", "olympus.copy_trade.wallet_discovery"),
            ("valhalla", "best wallet to copy in valhalla", "valhalla.copy_trade.wallet_discovery"),
        ):
            with self.subTest(question=question):
                ids = [
                    fact["id"] for fact in
                    retrieve_facts(question, product=product, intent="copy_trading", limit=_LIVE_LIMIT)
                ]
                self.assertIn(expected_id, ids)

    def test_links_render_into_the_model_evidence_text(self):
        facts = retrieve_facts(
            "How do I find wallets to follow in Olympus?",
            product="olympus", intent="copy_trading", limit=_LIVE_LIMIT,
        )
        evidence_text = bot._evidence_text(facts)
        for link in OLYMPUS_LINKS:
            self.assertIn(link, evidence_text)

    def test_unrelated_olympus_question_does_not_force_in_wallet_discovery(self):
        # The boost must be specific to the find/choose-wallet pattern, not a
        # blanket addition to every Olympus copy-trading question.
        facts = retrieve_facts(
            "why did my copied order only partially fill?",
            product="olympus", intent="orders", limit=_LIVE_LIMIT,
        )
        ids = [fact["id"] for fact in facts]
        self.assertNotIn("olympus.copy_trade.wallet_discovery", ids)


if __name__ == "__main__":
    unittest.main()
