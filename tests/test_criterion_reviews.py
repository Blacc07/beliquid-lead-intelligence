"""Offline tests for criterion-level reviewer input."""
import json
import tempfile
import unittest
from pathlib import Path

from beliquid.criterion_reviews import assessments_for_prospect, load_criterion_reviews
from beliquid.qualification import load_criteria_config

URL = "https://project.example/evidence"
TIMESTAMP = "2026-10-21T12:00:00Z"


class CriterionReviewTests(unittest.TestCase):
    def test_empty_file_loads_no_assessments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text('{"reviews":{}}', encoding="utf-8")
            self.assertEqual(load_criterion_reviews(path, load_criteria_config()), {})

    def test_loads_and_matches_review_case_insensitively(self):
        payload = {"reviews": {"SOLANA:So111": {
            "buying_trigger_and_timing": {
                "status": "confirmed", "evidence_urls": [URL],
                "evidence_timestamps": [TIMESTAMP], "note": "Official dated listing notice"
            }
        }}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            reviews = load_criterion_reviews(path, load_criteria_config())
        matched = assessments_for_prospect("solana", "so111", reviews)
        self.assertEqual(matched["buying_trigger_and_timing"]["status"], "confirmed")
        self.assertEqual(matched["buying_trigger_and_timing"]["evidence_urls"], [URL])

    def test_confirmed_requires_evidence(self):
        payload = {"reviews": {"solana:abc": {"service_fit_and_demonstrated_need": {"status": "confirmed"}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires evidence"):
                load_criterion_reviews(path, load_criteria_config())

    def test_not_present_requires_evidence(self):
        payload = {"reviews": {"solana:abc": {"market_activity_and_commercial_potential": {"status": "not_present"}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires evidence"):
                load_criterion_reviews(path, load_criteria_config())

    def test_timezone_required(self):
        payload = {"reviews": {"solana:abc": {"buying_trigger_and_timing": {
            "status": "confirmed", "evidence_urls": [URL],
            "evidence_timestamps": ["2026-10-21T12:00:00"]
        }}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "timezone"):
                load_criterion_reviews(path, load_criteria_config())

    def test_unknown_criterion_rejected(self):
        payload = {"reviews": {"solana:abc": {"fake_criterion": {"status": "unknown"}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown criterion"):
                load_criterion_reviews(path, load_criteria_config())

    def test_unknown_review_can_have_no_evidence(self):
        payload = {"reviews": {"solana:abc": {"buying_trigger_and_timing": {"status": "unknown"}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_criterion_reviews(path, load_criteria_config())
        self.assertEqual(loaded["solana:abc"]["buying_trigger_and_timing"]["status"], "unknown")

    def test_malformed_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Could not load"):
                load_criterion_reviews(path, load_criteria_config())


if __name__ == "__main__":
    unittest.main()
