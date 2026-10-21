"""Offline tests for the approved qualification configuration and conservative integration."""
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from beliquid.models import Evidence, ProspectRecord
from beliquid.qualification import load_criteria_config, qualify_discovered_record, summarize_qualification


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "qualification_criteria.json"


class QualificationTests(unittest.TestCase):
    def test_config_weights_and_keys_are_valid(self):
        config = load_criteria_config(CONFIG_PATH)
        self.assertEqual(config["status"], "approved_baseline_for_liquidity_services")
        self.assertEqual(sum(item["weight"] for item in config["criteria"]), 100)
        self.assertEqual([item["weight"] for item in config["criteria"]], [30, 20, 15, 15, 10, 10])

    def test_rejects_missing_safeguard(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["rules"]["no_automated_outreach"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "criteria.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "safeguards"):
                load_criteria_config(path)

    def test_market_metrics_do_not_create_score_or_evidence(self):
        record = ProspectRecord(
            project_name="Example",
            chain="ethereum",
            contract_address="0xabc",
            metrics={"liquidity_usd": 123456, "volume_24h_usd": 987654},
            evidence=(Evidence("DEX Screener", "https://dexscreener.com/", datetime.now(timezone.utc).isoformat(), "token_market_enrichment"),),
        )
        report = qualify_discovered_record(record, load_criteria_config(CONFIG_PATH))
        self.assertIsNone(report["score_percent"])
        self.assertEqual(report["score_status"], "insufficient_evidence")
        self.assertEqual(report["evidence_coverage_percent"], 0)
        self.assertTrue(report["outreach_enabled"] is False)
        self.assertIn("official_identity_unverified", report["review_flags"])
        self.assertTrue(all(item["status"] == "unknown" for item in report["criteria"]))
        self.assertEqual(report["discovery_evidence"][0]["source_url"], "https://dexscreener.com/")

    def test_summary_withholds_all_scores_until_review(self):
        record = ProspectRecord("Example", "ethereum", contract_address="0xabc")
        summary = summarize_qualification([record], load_criteria_config(CONFIG_PATH))
        self.assertEqual(summary["prospects_evaluated"], 1)
        self.assertEqual(summary["scores_issued"], 0)
        self.assertEqual(summary["scores_withheld_insufficient_evidence"], 1)
        self.assertFalse(summary["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
