"""Regression tests for fail-closed review batch validation and audit manifests."""
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from beliquid.models import ProspectRecord
from beliquid.review_export import write_review_exports
from beliquid.research_queue import write_research_queue
from beliquid.validate_review_batch import validate_batch, write_audit_manifest

URL = "https://evidence.example/review"
TIME = "2026-10-21T12:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = [
    "service_fit_and_demonstrated_need",
    "market_activity_and_commercial_potential",
    "buying_trigger_and_timing",
    "project_credibility_and_team_access",
    "growth_and_strategic_potential",
    "security_and_reputational_integrity",
]


class ValidateReviewBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        for config_name in ("qualification_criteria.json", "research_task_reviews.json"):
            shutil.copy(REPO_ROOT / "config" / config_name, self.config_dir / config_name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.records = [
            ProspectRecord("Held Candidate", "solana", contract_address="So111"),
            ProspectRecord("Boundary Candidate", "base", contract_address="0xabc"),
            ProspectRecord("Trigger Only Candidate", "arbitrum", contract_address="0xdef"),
        ]
        self.identity_reviews = {
            "reviews": {
                "solana:so111": {
                    "identity_status": "mismatch",
                    "identity_evidence_url": URL,
                    "identity_observed_at": TIME,
                    "risk_status": "concern",
                    "risk_evidence_url": URL,
                    "risk_observed_at": TIME,
                    "reviewer_note": "Independent hold fixture.",
                },
                "base:0xabc": {
                    "identity_status": "verified",
                    "identity_evidence_url": URL,
                    "identity_observed_at": TIME,
                    "risk_status": "clear",
                    "risk_evidence_url": URL,
                    "risk_observed_at": TIME,
                    "reviewer_note": "Verified fixture.",
                },
            }
        }
        self.criterion_reviews = {"reviews": {
            "solana:so111": {
                key: {
                    "status": "confirmed",
                    "evidence_urls": [URL, "https://evidence.example/second"],
                    "evidence_timestamps": [TIME, "2026-10-21T13:00:00+01:00"],
                    "note": "Reviewed evidence fixture.",
                    "review_flag": "second_review_requested",
                }
                for key in CONFIG_KEYS
            },
            "base:0xabc": {
                CONFIG_KEYS[0]: {"status": "confirmed", "evidence_urls": [URL], "evidence_timestamps": [TIME], "note": "Confirmed."},
                CONFIG_KEYS[1]: {"status": "not_present", "evidence_urls": [URL], "evidence_timestamps": [TIME], "note": "Not supported by checked evidence."},
                CONFIG_KEYS[3]: {"status": "confirmed", "evidence_urls": [URL], "evidence_timestamps": [TIME], "note": "Confirmed."},
            },
        }}
        self.trigger_reviews = {"reviews": {
            "arbitrum:0xdef": [{
                "trigger_type": "exchange_listing",
                "status": "verified",
                "evidence_url": URL,
                "observed_at": TIME,
                "summary": "Fixture trigger observation only.",
            }]
        }}
        self._write_inputs()
        self._generate_exports()

    def tearDown(self):
        self.temp.cleanup()

    def _write_inputs(self):
        for name, data in (
            ("criterion_reviews.json", self.criterion_reviews),
            ("identity_risk_reviews.json", self.identity_reviews),
            ("buying_trigger_reviews.json", self.trigger_reviews),
        ):
            (self.config_dir / name).write_text(json.dumps(data), encoding="utf-8")

    def _generate_exports(self):
        self.paths = write_review_exports(
            self.records,
            {"qualification": {"outreach_enabled": False}},
            self.artifacts,
            self.config_dir / "identity_risk_reviews.json",
            self.config_dir / "buying_trigger_reviews.json",
            self.config_dir / "criterion_reviews.json",
        )
        write_research_queue(self.artifacts / "prospect-review.json", self.artifacts, self.config_dir / "research_task_reviews.json")
        (self.artifacts / "automated-research.json").write_text(json.dumps({"schema_version": 1, "records": [], "outreach_enabled": False}), encoding="utf-8")
        (self.artifacts / "security-research.json").write_text(json.dumps({"schema_version": 1, "records": [], "outreach_enabled": False}), encoding="utf-8")
        (self.artifacts / "trigger-research.json").write_text(json.dumps({"schema_version": 1, "records": [], "outreach_enabled": False}), encoding="utf-8")
        (self.artifacts / "criterion-evidence.json").write_text(json.dumps({"schema_version": 1, "records": [], "outreach_enabled": False}), encoding="utf-8")
        (self.artifacts / "research-task-ledger.json").write_text(json.dumps({"schema_version": 1, "reviews": {}}), encoding="utf-8")

    def test_validates_threshold_boundary_holds_trigger_separation_and_parity(self):
        result = validate_batch(self.artifacts, self.root)
        self.assertEqual(result["validation_status"], "passed")
        self.assertEqual(result["records_validated"], 3)
        self.assertEqual(result["manual_holds"], 1)
        self.assertEqual(result["scores_issued"], 2)
        self.assertEqual(result["scores_withheld"], 1)
        self.assertFalse(result["outreach_enabled"])

        payload = json.loads((self.artifacts / "prospect-review.json").read_text(encoding="utf-8"))
        records = {f"{r['chain']}:{r['contract_address'].casefold()}": r for r in payload["records"]}
        held = records["solana:so111"]
        self.assertEqual(held["action_route"], "manual_hold")
        self.assertEqual(held["qualification"]["score_percent"], 100.0)
        self.assertEqual(held["qualification"]["evidence_coverage_percent"], 100.0)
        self.assertFalse(held["qualification"]["outreach_enabled"])
        self.assertEqual(held["qualification"]["criteria"][0]["evidence_urls"], [URL, "https://evidence.example/second"])
        self.assertEqual(held["qualification"]["criteria"][0]["reviewer_review_flag"], "second_review_requested")

        boundary = records["base:0xabc"]
        self.assertEqual(boundary["qualification"]["evidence_coverage_percent"], 60.0)
        self.assertEqual(boundary["qualification"]["score_status"], "scored")
        self.assertEqual(boundary["action_route"], "business_development_review")

        trigger_only = records["arbitrum:0xdef"]
        self.assertEqual(trigger_only["buying_triggers"]["status"], "verified")
        self.assertTrue(all(c["status"] == "unknown" for c in trigger_only["qualification"]["criteria"]))
        self.assertIsNone(trigger_only["qualification"]["score_percent"])
        self.assertEqual(trigger_only["action_route"], "research")

    def test_review_key_not_in_current_batch_fails_closed(self):
        self.identity_reviews["reviews"]["ethereum:wrong-contract"] = {
            "identity_status": "verified",
            "identity_evidence_url": URL,
            "identity_observed_at": TIME,
            "risk_status": "unknown",
        }
        self._write_inputs()
        self._generate_exports()
        with self.assertRaisesRegex(ValueError, "do not match any prospect"):
            validate_batch(self.artifacts, self.root)

    def test_csv_tampering_fails_parity_validation(self):
        with (self.artifacts / "prospect-review.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            fields = list(rows[0])
        rows[0]["action_route"] = "business_development_review"
        with (self.artifacts / "prospect-review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, "CSV/JSON mismatch"):
            validate_batch(self.artifacts, self.root)

    def test_audit_manifest_records_run_context_and_hashes(self):
        result = validate_batch(self.artifacts, self.root)
        old = dict(os.environ)
        try:
            os.environ["GITHUB_RUN_ID"] = "test-run-123"
            os.environ["GITHUB_SHA"] = "test-sha"
            path = write_audit_manifest(self.artifacts, result, self.root)
        finally:
            os.environ.clear()
            os.environ.update(old)
        (self.artifacts / "automated-criterion-assessment.json").write_text(json.dumps({"records": []}), encoding="utf-8")
        (self.artifacts / "automated-criterion-reviews.json").write_text(json.dumps({"reviews": {}}), encoding="utf-8")
        result = validate_batch(self.artifacts, self.root)
        path = write_audit_manifest(self.artifacts, result, self.root)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflow"]["run_id"], "test-run-123")
        self.assertEqual(manifest["workflow"]["commit_sha"], "test-sha")
        self.assertIn("config/criterion_reviews.json", manifest["review_input_sha256"])
        self.assertIn("prospect-review.json", manifest["export_sha256"])
        self.assertIn("automated-research.json", manifest["export_sha256"])
        self.assertIn("security-research.json", manifest["export_sha256"])
        self.assertIn("trigger-research.json", manifest["export_sha256"])
        self.assertIn("criterion-evidence.json", manifest["export_sha256"])
        self.assertIn("research-task-ledger.json", manifest["export_sha256"])
        self.assertIn("automated-criterion-assessment.json", manifest["export_sha256"])
        self.assertIn("automated-criterion-reviews.json", manifest["export_sha256"])
        self.assertFalse(manifest["validation"]["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
