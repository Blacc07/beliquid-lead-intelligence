"""Offline tests for evidence-backed buying-trigger reviews."""
import json
import tempfile
import unittest
from pathlib import Path

from beliquid.buying_triggers import (
    BuyingTrigger, BuyingTriggerAssessment, assessment_for_prospect,
    load_buying_trigger_reviews,
)

URL = "https://project.example/announcements/listing"
TIMESTAMP = "2026-10-21T12:00:00Z"


class BuyingTriggerTests(unittest.TestCase):
    def test_unknown_default_is_not_buying_intent(self):
        assessment = BuyingTriggerAssessment()
        self.assertEqual(assessment.status, "unknown")
        self.assertEqual(assessment.verified_count, 0)
        self.assertFalse(assessment.to_dict()["buying_intent_confirmed_by_market_metrics"])

    def test_verified_trigger_requires_evidence_and_summary(self):
        with self.assertRaisesRegex(ValueError, "evidence URL"):
            BuyingTrigger(trigger_type="exchange_listing", status="verified")

    def test_timestamp_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            BuyingTrigger(trigger_type="exchange_listing", status="verified",
                          evidence_url=URL, observed_at="2026-10-21T12:00:00",
                          summary="Listing announcement")

    def test_non_http_evidence_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            BuyingTrigger(status="inferred", evidence_url="javascript:alert(1)",
                          observed_at=TIMESTAMP, summary="Possible listing")

    def test_invalid_type_and_status_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "trigger_type"):
            BuyingTrigger(trigger_type="market_hype")
        with self.assertRaisesRegex(ValueError, "status"):
            BuyingTrigger(status="certain")

    def test_event_date_must_be_calendar_date(self):
        with self.assertRaisesRegex(ValueError, "calendar date"):
            BuyingTrigger(status="verified", evidence_url=URL, observed_at=TIMESTAMP,
                          summary="Listing", event_date="not-a-date")

    def test_unknown_trigger_rejects_partial_or_malformed_evidence(self):
        with self.assertRaisesRegex(ValueError, "timestamp"):
            BuyingTrigger(status="unknown", evidence_url=URL)
        with self.assertRaisesRegex(ValueError, "HTTP"):
            BuyingTrigger(status="unknown", evidence_url="javascript:bad", observed_at=TIMESTAMP)

    def test_verified_status_takes_precedence_over_inferred(self):
        inferred = BuyingTrigger("venue_expansion", "inferred", URL, TIMESTAMP,
                                 summary="Project may expand venues")
        verified = BuyingTrigger("exchange_listing", "verified", URL, TIMESTAMP,
                                 summary="Official listing announcement")
        assessment = BuyingTriggerAssessment((inferred, verified))
        self.assertEqual(assessment.status, "verified")
        self.assertEqual(assessment.verified_count, 1)
        self.assertEqual(assessment.inferred_count, 1)

    def test_load_and_match_review_case_insensitively(self):
        payload = {"reviews": {"SOLANA:So111": [{
            "trigger_type": "exchange_listing", "status": "verified",
            "evidence_url": URL, "observed_at": TIMESTAMP,
            "event_date": "2026-10-25", "summary": "Official listing announcement",
        }]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            reviews = load_buying_trigger_reviews(path)
        assessment = assessment_for_prospect("solana", "so111", reviews)
        self.assertEqual(assessment.status, "verified")
        self.assertEqual(assessment.triggers[0].event_date, "2026-10-25")

    def test_invalid_review_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text('{"reviews":{"solana:abc":[{"status":"verified"}]}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence URL"):
                load_buying_trigger_reviews(path)

    def test_unknown_status_can_be_recorded_without_claiming_event(self):
        trigger = BuyingTrigger(trigger_type="other", status="unknown")
        self.assertEqual(trigger.to_dict()["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
