"""Safeguard-first research queue ordering and completion-ledger tests."""
import unittest
from beliquid.research_queue import build_research_queue, record_fingerprint


def prospect(name, identity="unknown", risk="unknown", route="research", priority="low", verified_count=0, score=None, coverage=0):
    return {"project_name": name, "chain": "ethereum", "contract_address": "0x" + name.lower().replace(" ", ""),
        "identity_risk": {"identity_status": identity, "risk_status": risk, "action_route": route},
        "action_route": route, "market_research_priority": {"priority": priority, "signals": ["activity"]},
        "buying_triggers": {"status": "verified" if verified_count else "unknown", "verified_count": verified_count},
        "qualification": {"score_percent": score, "score_status": "scored" if score is not None else "insufficient_evidence", "evidence_coverage_percent": coverage, "outreach_enabled": False}}


def completion(record, task, outcome="inconclusive", fingerprint=None):
    return {"status": "completed", "reviewer": "reviewer-1", "completed_at": "2026-10-21T10:00:00Z",
        "outcome": outcome, "evidence_urls": ["https://example.org/evidence"],
        "evidence_timestamps": ["2026-10-21T09:00:00Z"],
        "input_fingerprint": fingerprint or record_fingerprint(record)}


class ResearchQueueTests(unittest.TestCase):
    def test_manual_hold_precedes_and_blocks_downstream_tasks(self):
        queue = build_research_queue({"records": [prospect("High", "verified", "clear", "business_development_review", "high"), prospect("Hold", "mismatch", "clear", "manual_hold", "high", score=90, coverage=100)]})
        self.assertEqual(queue["tasks"][0]["task"], "resolve_manual_hold")
        self.assertTrue(queue["tasks"][0]["blocked_by_hold"])
        self.assertFalse(queue["tasks"][0]["outreach_enabled"])

    def test_identity_and_risk_precede_market_priority(self):
        queue = build_research_queue({"records": [prospect("Unknown", priority="high"), prospect("Verified", "verified", "clear", "business_development_review", "high")]})
        by_name = {x["project_name"]: x for x in queue["tasks"]}
        self.assertEqual(by_name["Unknown"]["task"], "verify_identity_and_risk")
        self.assertEqual(by_name["Verified"]["task"], "investigate_market_quality")
        self.assertLess(by_name["Unknown"]["task_order"], by_name["Verified"]["task_order"])

    def test_clear_medium_researches_triggers_then_criteria(self):
        item = build_research_queue({"records": [prospect("Clear", "verified", "clear", "business_development_review", "medium")]})["tasks"][0]
        self.assertEqual(item["task"], "research_buying_triggers")
        item = build_research_queue({"records": [prospect("Trigger", "verified", "clear", "business_development_review", "medium", verified_count=1, coverage=45)]})["tasks"][0]
        self.assertEqual(item["task"], "complete_criterion_evidence")

    def test_eligible_requires_independent_review_and_never_outreach(self):
        item = build_research_queue({"records": [prospect("Eligible", "verified", "clear", "business_development_review", "low", verified_count=1, score=75, coverage=80)]})["tasks"][0]
        self.assertEqual(item["task"], "independent_human_review")
        self.assertFalse(item["outreach_enabled"])

    def test_unknowns_preserved_duplicate_rejected(self):
        row = prospect("Unknown")
        item = build_research_queue({"records": [row]})["tasks"][0]
        self.assertEqual((item["identity_status"], item["risk_status"]), ("unknown", "unknown"))
        with self.assertRaisesRegex(ValueError, "duplicate prospect"):
            build_research_queue({"records": [row, row]})

    def test_records_required(self):
        with self.assertRaisesRegex(ValueError, "records list"):
            build_research_queue({})

    def test_completed_market_task_is_suppressed_for_same_snapshot(self):
        row = prospect("Market", "verified", "clear", "business_development_review", "high")
        ledger = {"schema_version": 1, "reviews": {"ethereum:" + row["contract_address"]: {
            "investigate_market_quality": completion(row, "investigate_market_quality")}}}
        item = build_research_queue({"records": [row]}, ledger)["tasks"][0]
        self.assertEqual(item["task"], "research_buying_triggers")

    def test_changed_snapshot_reopens_completed_task(self):
        row = prospect("Market", "verified", "clear", "business_development_review", "high")
        ledger = {"schema_version": 1, "reviews": {"ethereum:" + row["contract_address"]: {
            "investigate_market_quality": completion(row, "investigate_market_quality")}}}
        row["market_research_priority"]["signals"].append("new signal")
        item = build_research_queue({"records": [row]}, ledger)["tasks"][0]
        self.assertEqual(item["task"], "investigate_market_quality")

    def test_completed_identity_research_does_not_clear_unknown_status(self):
        row = prospect("Unknown")
        ledger = {"schema_version": 1, "reviews": {"ethereum:" + row["contract_address"]: {
            "verify_identity_and_risk": completion(row, "verify_identity_and_risk")}}}
        item = build_research_queue({"records": [row]}, ledger)["tasks"][0]
        self.assertEqual(item["task"], "escalate_unresolved_identity_risk")
        self.assertTrue(item["blocked_by_hold"])
        self.assertEqual(item["identity_status"], "unknown")
        self.assertFalse(item["outreach_enabled"])

    def test_manual_hold_overrides_any_completed_research(self):
        row = prospect("Hold", "mismatch", "clear", "manual_hold", "high")
        ledger = {"schema_version": 1, "reviews": {"ethereum:" + row["contract_address"]: {
            "investigate_market_quality": completion(row, "investigate_market_quality")}}}
        item = build_research_queue({"records": [row]}, ledger)["tasks"][0]
        self.assertEqual(item["task"], "resolve_manual_hold")

    def test_bad_ledger_fails_closed(self):
        row = prospect("Unknown")
        ledger = {"schema_version": 1, "reviews": {"ethereum:" + row["contract_address"]: {
            "verify_identity_and_risk": {"status": "completed"}}}}
        with self.assertRaisesRegex(ValueError, "requires non-empty reviewer"):
            build_research_queue({"records": [row]}, ledger)


if __name__ == "__main__":
    unittest.main()
