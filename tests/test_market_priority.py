"""Offline tests for explainable market research priority triage."""
import unittest

from beliquid.market_priority import prioritize_market_research


class MarketResearchPriorityTests(unittest.TestCase):
    def test_low_liquidity_and_strong_activity_flags_research(self):
        result = prioritize_market_research({"volume_24h_usd": 136139.62, "liquidity_usd": 14613.64})
        self.assertEqual(result["priority"], "high")
        self.assertIn("activity_with_low_reported_liquidity", result["signals"])
        self.assertIsNone(result["qualification_score"])
        self.assertFalse(result["buying_intent_verified"])

    def test_missing_metrics_are_insufficient_not_zero(self):
        result = prioritize_market_research({"volume_24h_usd": None, "liquidity_usd": None})
        self.assertEqual(result["priority"], "insufficient_data")
        self.assertIn("volume_unknown", result["signals"])
        self.assertIn("liquidity_unknown", result["signals"])

    def test_volume_alone_does_not_create_high_priority(self):
        result = prioritize_market_research({"volume_24h_usd": 30000, "liquidity_usd": None})
        self.assertEqual(result["priority"], "medium")
        self.assertNotIn("activity_with_low_reported_liquidity", result["signals"])

    def test_zero_liquidity_with_activity_is_flagged_for_verification(self):
        result = prioritize_market_research({"volume_24h_usd": 50000, "liquidity_usd": 0})
        self.assertEqual(result["priority"], "high")
        self.assertIn("reported_zero_liquidity_with_activity", result["signals"])

    def test_zero_volume_is_not_treated_as_missing(self):
        result = prioritize_market_research({"volume_24h_usd": 0, "liquidity_usd": 0})
        self.assertEqual(result["priority"], "low")
        self.assertNotIn("volume_unknown", result["signals"])

    def test_ratio_is_only_calculated_when_liquidity_is_positive(self):
        result = prioritize_market_research({"volume_24h_usd": 30000, "liquidity_usd": 10000})
        self.assertEqual(result["volume_to_liquidity_ratio"], 3.0)
        self.assertEqual(result["priority"], "high")


if __name__ == "__main__":
    unittest.main()
