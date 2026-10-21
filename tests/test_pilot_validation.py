"""Tests for the controlled pilot-validation report."""
import unittest

from beliquid.pilot_validation import assess_record, build_report, CRITERIA

URL = "https://evidence.example/source"
TIME = "2026-10-21T12:00:00Z"


def record(name="Candidate", statuses=None, identity="unknown", risk="unknown", flags=None):
    statuses = statuses or {}
    criteria = []
    for key in CRITERIA:
        status = statuses.get(key, "unknown")
        criteria.append({
            "criterion": key,
            "status": status,
            "evidence_urls": [URL] if status != "unknown" else [],
            "evidence_timestamps": [TIME] if status != "unknown" else [],
            "reviewer_review_flag": None,
        })
    return {
        "project_name": name,
        "chain": "ethereum",
        "contract_address": "0xabc",
        "action_route": "manual_hold" if identity == "mismatch" or risk == "concern" else (
            "business_development_review" if identity == "verified" and risk == "clear" else "research"
        ),
        "identity_risk": {
            "identity_status": identity, "risk_status": risk,
            "identity_evidence_url": URL if identity != "unknown" else None,
            "identity_observed_at": TIME if identity != "unknown" else None,
            "risk_evidence_url": URL if risk != "unknown" else None,
            "risk_observed_at": TIME if risk != "unknown" else None,
            "review_flags": [],
        },
        "buying_triggers": {"status": "unknown", "trigger_count": 0},
        "qualification": {
            "criteria": criteria, "review_flags": flags or [],
            "score_status": "scored" if all(x != "unknown" for x in statuses.values()) and len(statuses) == 6 else "insufficient_evidence",
            "score_percent": 70 if len(statuses) == 6 else None,
            "evidence_coverage_percent": 100 if len(statuses) == 6 else 0,
            "outreach_enabled": False,
        },
    }


class PilotValidationTests(unittest.TestCase):
    def test_empty_record_is_not_started_and_unknowns_remain_unknown(self):
        result = assess_record(record())
        self.assertEqual(result["review_completion_status"], "not_started")
        self.assertEqual(result["criteria_unknown"], 6)
        self.assertEqual(result["score_percent"], None)
        self.assertFalse(result["outreach_enabled"])

    def test_fully_reviewed_record_is_ready_for_second_review_not_approved(self):
        statuses = {key: "confirmed" for key in CRITERIA}
        result = assess_record(record(statuses=statuses, identity="verified", risk="clear"))
        self.assertEqual(result["review_completion_status"], "ready_for_second_review")
        self.assertTrue(result["criteria_evidence_complete"])
        self.assertFalse(result["outreach_enabled"])

    def test_manual_hold_overrides_review_completion(self):
        statuses = {key: "confirmed" for key in CRITERIA}
        result = assess_record(record(statuses=statuses, identity="mismatch", risk="concern"))
        self.assertEqual(result["review_completion_status"], "blocked_manual_hold")

    def test_review_flags_prevent_second_review_ready(self):
        statuses = {key: "confirmed" for key in CRITERIA}
        candidate = record(statuses=statuses, identity="verified", risk="clear")
        candidate["identity_risk"]["review_flags"] = ["evidence_outdated"]
        result = assess_record(candidate)
        self.assertEqual(result["review_completion_status"], "in_progress")

    def test_report_separates_engineering_from_evidence_quality(self):
        report = build_report({"records": [record()]}, {"validation": {
            "validation_status": "passed", "records_validated": 1, "csv_json_field_comparisons": 99
        }})
        self.assertEqual(report["engineering_validation"]["validation_status"], "passed")
        self.assertEqual(report["prospect_evidence_quality"]["criteria_unknown"], 6)
        self.assertFalse(report["prospect_evidence_quality"]["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
