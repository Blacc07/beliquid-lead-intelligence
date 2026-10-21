"""Offline tests for full-batch human review exports."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from beliquid.models import Evidence, ProspectRecord
from beliquid.review_export import write_review_exports


URL = "https://project.example/official-identity"
TIMESTAMP = "2026-10-21T12:00:00Z"


class ReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            ProspectRecord(
                project_name="Candidate One",
                chain="solana",
                contract_address="So111",
                metrics={"volume_24h_usd": 0, "liquidity_usd": None},
                evidence=(Evidence(
                    "DEX Screener",
                    "https://dexscreener.com/solana/So111",
                    "2026-10-21T13:00:00Z",
                    "token_profile_discovery",
                ),),
            ),
            ProspectRecord("Candidate Two", "base", contract_address="0xabc"),
        ]

    def test_exports_unknown_identity_risk_and_qualification_conservatively(self):
        with tempfile.TemporaryDirectory() as directory:
            review_path = Path(directory) / "reviews.json"
            review_path.write_text('{"reviews":{}}', encoding="utf-8")
            output = Path(directory) / "out"
            summary = {"qualification": {"prospects_evaluated": 2}}
            paths = write_review_exports(self.records, summary, output, review_path)
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 6)
            self.assertEqual(payload["records_exported"], 2)
            self.assertEqual(len(payload["records"]), 2)
            first = payload["records"][0]
            self.assertEqual(first["triage_bucket"], "identity_verification_required")
            self.assertEqual(first["action_route"], "research")
            self.assertEqual(first["identity_risk"]["identity_status"], "unknown")
            self.assertEqual(first["identity_risk"]["risk_status"], "unknown")
            self.assertIsNone(first["qualification"]["score_percent"])
            self.assertTrue(all(c["status"] == "unknown" for c in first["qualification"]["criteria"]))
            self.assertFalse(first["qualification"]["outreach_enabled"])
            self.assertEqual(payload["identity_risk_summary"]["research_count"], 2)
            self.assertEqual(payload["market_research_priority_summary"]["prospects_triaged"], 2)
            self.assertEqual(payload["buying_trigger_summary"]["prospects_by_status"]["unknown"], 2)
            self.assertEqual(first["buying_triggers"]["status"], "unknown")
            self.assertEqual(first["buying_triggers"]["trigger_count"], 0)
            self.assertEqual(first["market_research_priority"]["priority"], "low")
            self.assertIsNone(first["market_research_priority"]["qualification_score"])
            self.assertFalse(first["market_research_priority"]["buying_intent_verified"])

            with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["service_fit_and_demonstrated_need_status"], "unknown")
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_status"], "unknown")
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_evidence_url"], "")
            self.assertEqual(rows[0]["volume_24h_usd"], "0")
            self.assertEqual(rows[0]["score_percent"], "")
            self.assertEqual(rows[0]["identity_status"], "unknown")
            self.assertEqual(rows[0]["risk_status"], "unknown")
            self.assertEqual(rows[0]["action_route"], "research")
            self.assertEqual(rows[0]["market_research_priority"], "low")
            self.assertEqual(rows[0]["buying_trigger_status"], "unknown")
            self.assertEqual(rows[0]["buying_trigger_count"], "0")
            self.assertEqual(json.loads(rows[0]["buying_triggers_json"]), [])
            self.assertIn("official_identity_unverified", rows[0]["identity_risk_flags"])
            self.assertTrue(Path(paths["summary"]).exists())

    def test_reviewed_risk_concern_appears_as_manual_hold_in_both_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            review_path = Path(directory) / "reviews.json"
            review_path.write_text(json.dumps({"reviews": {
                "SOLANA:so111": {
                    "identity_status": "verified",
                    "identity_evidence_url": URL,
                    "identity_observed_at": TIMESTAMP,
                    "risk_status": "concern",
                    "risk_evidence_url": URL,
                    "risk_observed_at": TIMESTAMP,
                    "reviewer_note": "Documented concern for human follow-up.",
                }
            }}), encoding="utf-8")
            paths = write_review_exports(self.records, {}, Path(directory) / "out", review_path)
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            first = payload["records"][0]
            self.assertEqual(first["identity_risk"]["risk_status"], "concern")
            self.assertEqual(first["action_route"], "manual_hold")
            self.assertEqual(payload["identity_risk_summary"]["manual_hold_count"], 1)
            with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["action_route"], "manual_hold")
            self.assertEqual(rows[0]["risk_status"], "concern")
            self.assertEqual(rows[0]["identity_risk_reviewer_note"], "Documented concern for human follow-up.")


    def test_reviewed_trigger_is_exported_but_does_not_change_route_or_score(self):
        with tempfile.TemporaryDirectory() as directory:
            identity_path = Path(directory) / "identity.json"
            identity_path.write_text('{"reviews":{}}', encoding="utf-8")
            trigger_path = Path(directory) / "triggers.json"
            trigger_path.write_text(json.dumps({"reviews": {
                "SOLANA:so111": [{
                    "trigger_type": "exchange_listing",
                    "status": "verified",
                    "evidence_url": URL,
                    "observed_at": TIMESTAMP,
                    "event_date": "2026-10-25",
                    "summary": "Official exchange listing announcement",
                }]
            }}), encoding="utf-8")
            paths = write_review_exports(
                self.records, {}, Path(directory) / "out", identity_path, trigger_path
            )
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            first = payload["records"][0]
            self.assertEqual(first["buying_triggers"]["status"], "verified")
            self.assertEqual(first["buying_triggers"]["verified_count"], 1)
            self.assertEqual(first["action_route"], "research")
            self.assertIsNone(first["qualification"]["score_percent"])
            self.assertFalse(first["qualification"]["outreach_enabled"])
            self.assertEqual(payload["buying_trigger_summary"]["verified_trigger_observations"], 1)

    def test_criterion_review_is_exported_and_can_contribute_to_score(self):
        with tempfile.TemporaryDirectory() as directory:
            identity_path = Path(directory) / "identity.json"
            identity_path.write_text('{"reviews":{}}', encoding="utf-8")
            trigger_path = Path(directory) / "triggers.json"
            trigger_path.write_text('{"reviews":{}}', encoding="utf-8")
            criterion_path = Path(directory) / "criteria.json"
            criterion_path.write_text(json.dumps({"reviews": {
                "SOLANA:so111": {
                    "service_fit_and_demonstrated_need": {
                        "status": "confirmed", "evidence_urls": [URL],
                        "evidence_timestamps": [TIMESTAMP],
                        "note": "Reviewed market-quality evidence",
                    },
                    "market_activity_and_commercial_potential": {
                        "status": "not_present", "evidence_urls": [URL],
                        "evidence_timestamps": [TIMESTAMP],
                        "note": "Reviewed activity evidence",
                    },
                }
            }}), encoding="utf-8")
            paths = write_review_exports(
                self.records, {}, Path(directory) / "out", identity_path, trigger_path, criterion_path
            )
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            first = payload["records"][0]
            self.assertEqual(first["qualification"]["criteria"][0]["status"], "confirmed")
            self.assertEqual(first["qualification"]["criteria"][1]["status"], "not_present")
            self.assertEqual(first["qualification"]["evidence_coverage_percent"], 45)
            self.assertIsNone(first["qualification"]["score_percent"])
            self.assertEqual(payload["criterion_review_summary"]["prospects_with_any_criterion_review"], 1)
            with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_status"], "confirmed")
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_evidence_url"], URL)
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_reviewer_note"], "Reviewed market-quality evidence")

    def test_malformed_criterion_review_fails_export_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            criterion_path = Path(directory) / "criteria.json"
            criterion_path.write_text('{"reviews":{"solana:abc":{"fake_criterion":{"status":"confirmed"}}}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown criterion"):
                write_review_exports(self.records, {}, Path(directory) / "out",
                                     criterion_reviews_path=criterion_path)

    def test_malformed_trigger_review_fails_export_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            trigger_path = Path(directory) / "triggers.json"
            trigger_path.write_text('{"reviews":{"solana:abc":[{"status":"verified"}]}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence URL"):
                write_review_exports(self.records, {}, Path(directory) / "out",
                                     buying_trigger_reviews_path=trigger_path)


if __name__ == "__main__":
    unittest.main()
