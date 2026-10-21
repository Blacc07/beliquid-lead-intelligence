"""Offline tests for the proposed BeLiquid qualification configuration and conservative integration."""
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
        self.assertEqual(config["status"], "proposed_pilot_baseline")
        self.assertEqual(sum(item["weight"] for item in config["criteria"]), 100)
        self.assertEqual(
            [item["weight"] for item in config["criteria"]],
            [25, 20, 20, 15, 10, 10],
        )
        self.assertEqual(
            [item["key"] for item in config["criteria"]],
            [
                "service_fit_and_demonstrated_need",
                "market_activity_and_commercial_potential",
                "buying_trigger_and_timing",
                "project_credibility_and_team_access",
                "growth_and_strategic_potential",
                "security_and_reputational_integrity",
            ],
        )
        self.assertIn("manual_hold", config["action_routes"])
        self.assertIn("verified", config["trigger_labels"])

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

    def test_reviewed_criterion_is_scored_only_with_evidence_and_weighted_config(self):
        record = ProspectRecord("Example", "ethereum", contract_address="0xabc")
        config = load_criteria_config(CONFIG_PATH)
        reviews = {
            "service_fit_and_demonstrated_need": {
                "status": "confirmed", "evidence_urls": ["https://example.org/spreads"],
                "evidence_timestamps": ["2026-10-21T12:00:00Z"],
                "note": "Observed wide spread and shallow depth",
            },
            "market_activity_and_commercial_potential": {
                "status": "not_present", "evidence_urls": ["https://example.org/activity"],
                "evidence_timestamps": ["2026-10-21T12:00:00Z"],
                "note": "Reviewed sample shows low sustained activity",
            },
        }
        report = qualify_discovered_record(record, config, reviews)
        self.assertEqual(report["criteria"][0]["status"], "confirmed")
        self.assertEqual(report["criteria"][0]["weight"], 25)
        self.assertEqual(report["criteria"][1]["status"], "not_present")
        self.assertEqual(report["evidence_coverage_percent"], 45)
        self.assertIsNone(report["score_percent"])
        self.assertEqual(report["score_status"], "insufficient_evidence")
        self.assertFalse(report["outreach_enabled"])

    def test_score_issued_only_when_reviewed_coverage_reaches_threshold(self):
        record = ProspectRecord("Example", "ethereum", contract_address="0xabc")
        config = load_criteria_config(CONFIG_PATH)
        reviews = {}
        for item in config["criteria"][:4]:
            reviews[item["key"]] = {
                "status": "confirmed",
                "evidence_urls": ["https://example.org/" + item["key"]],
                "evidence_timestamps": ["2026-10-21T12:00:00Z"],
            }
        report = qualify_discovered_record(record, config, reviews)
        self.assertEqual(report["evidence_coverage_percent"], 80)
        self.assertEqual(report["score_percent"], 100.0)
        self.assertEqual(report["score_status"], "scored")
        self.assertFalse(report["outreach_enabled"])

    def test_unknown_criterion_key_rejected(self):
        record = ProspectRecord("Example", "ethereum", contract_address="0xabc")
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            qualify_discovered_record(record, load_criteria_config(CONFIG_PATH), {"bogus": {"status": "confirmed"}})

    def test_summary_withholds_all_scores_until_review(self):
        record = ProspectRecord("Example", "ethereum", contract_address="0xabc")
        summary = summarize_qualification([record], load_criteria_config(CONFIG_PATH))
        self.assertEqual(summary["prospects_evaluated"], 1)
        self.assertEqual(summary["scores_issued"], 0)
        self.assertEqual(summary["scores_withheld_insufficient_evidence"], 1)
        self.assertFalse(summary["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
