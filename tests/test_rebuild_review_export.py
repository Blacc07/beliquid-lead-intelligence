"""Integration tests for source-backed automated assessments flowing into qualification exports."""
import json
from pathlib import Path
import tempfile
import unittest

from beliquid.automated_criterion_assessment import assess_criterion_reviews
from beliquid.models import ProspectRecord
from beliquid.rebuild_review_export import rebuild_exports
from beliquid.review_export import write_review_exports
from beliquid.qualification import load_criteria_config


STAMP1 = "2026-10-20T12:00:00Z"
STAMP2 = "2026-10-21T12:00:00Z"


class RebuildReviewExportTests(unittest.TestCase):
    def test_corrobated_event_changes_criterion_status_but_respects_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            initial = write_review_exports(
                [ProspectRecord("Alpha Protocol", "base", contract_address="0xabc123456789abcdef", token_symbol="ALPHA")],
                {"qualification": {"outreach_enabled": False}}, artifacts,
            )
            prospect_payload = json.loads((artifacts / "prospect-review.json").read_text(encoding="utf-8"))
            row = prospect_payload["records"][0]
            candidates = [
                {"trigger_type": "exchange_listing", "status": "candidate_only", "provider": "CoinDesk",
                 "source_scope": "global_news", "date_verified": True,
                 "title": "Alpha Protocol ALPHA listing announced",
                 "summary_excerpt": "ALPHA 0xabc123456789abcdef exchange listing",
                 "event_url": "https://www.coindesk.com/news/alpha-listing", "published_at": STAMP1, "observed_at": STAMP1},
                {"trigger_type": "exchange_listing", "status": "candidate_only", "provider": "Cointelegraph",
                 "source_scope": "global_news", "date_verified": True,
                 "title": "Alpha Protocol ALPHA listing announced",
                 "summary_excerpt": "ALPHA 0xabc123456789abcdef exchange listing",
                 "event_url": "https://cointelegraph.com/news/alpha-listing", "published_at": STAMP2, "observed_at": STAMP2},
            ]
            triggers = {"records": [{"chain": row["chain"], "contract_address": row["contract_address"],
                                     "project_name": row["project_name"], "trigger_candidates": candidates}]}
            criteria = load_criteria_config()
            assessment = assess_criterion_reviews(prospect_payload, triggers, criteria, STAMP2)
            review_path = artifacts / "automated-criterion-reviews.json"
            review_path.write_text(json.dumps(assessment["criterion_reviews"]), encoding="utf-8")
            result = rebuild_exports(artifacts / "prospect-review.json", artifacts / "pipeline-summary.json",
                                     artifacts, review_path)
            final = json.loads((artifacts / "prospect-review.json").read_text(encoding="utf-8"))
            prospect = final["records"][0]
            criterion = next(item for item in prospect["qualification"]["criteria"]
                             if item["criterion"] == "buying_trigger_and_timing")
            self.assertEqual(result["status"], "written")
            self.assertEqual(criterion["status"], "confirmed")
            self.assertEqual(criterion["evidence_urls"], [item["event_url"] for item in candidates])
            self.assertEqual(prospect["qualification"]["evidence_coverage_percent"], 20.0)
            self.assertIsNone(prospect["qualification"]["score_percent"])
            self.assertEqual(prospect["qualification"]["score_status"], "insufficient_evidence")
            self.assertFalse(prospect["qualification"]["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
