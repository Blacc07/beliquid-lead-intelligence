"""Offline tests for full-batch human review exports."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from beliquid.models import Evidence, ProspectRecord
from beliquid.review_export import write_review_exports


class ReviewExportTests(unittest.TestCase):
    def test_exports_full_batch_with_unknown_criteria_and_no_score(self):
        records = [
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
        with tempfile.TemporaryDirectory() as directory:
            paths = write_review_exports(records, {"qualification": {"prospects_evaluated": 2}}, directory)
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["records_exported"], 2)
            self.assertEqual(len(payload["records"]), 2)
            first = payload["records"][0]
            self.assertEqual(first["triage_bucket"], "identity_verification_required")
            self.assertIsNone(first["qualification"]["score_percent"])
            self.assertTrue(all(c["status"] == "unknown" for c in first["qualification"]["criteria"]))
            self.assertFalse(first["qualification"]["outreach_enabled"])

            with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["service_fit_and_demonstrated_need_status"], "unknown")
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_status"], "unknown")
            self.assertEqual(rows[0]["review_service_fit_and_demonstrated_need_evidence_url"], "")
            self.assertEqual(rows[0]["volume_24h_usd"], "0")
            self.assertEqual(rows[0]["score_percent"], "")
            self.assertTrue(Path(paths["summary"]).exists())


if __name__ == "__main__":
    unittest.main()
