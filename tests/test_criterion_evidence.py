"""Tests for six-criterion candidate evidence aggregation."""
import unittest

from beliquid.criterion_evidence import build_criterion_evidence


CRITERIA = {
    "name": "Test scorecard",
    "minimum_evidence_coverage_percent": 60,
    "criteria": [
        {"key": "service_fit_and_demonstrated_need", "label": "Service fit", "weight": 25},
        {"key": "market_activity_and_commercial_potential", "label": "Market activity", "weight": 20},
        {"key": "buying_trigger_and_timing", "label": "Buying trigger", "weight": 20},
        {"key": "project_credibility_and_team_access", "label": "Credibility", "weight": 15},
        {"key": "growth_and_strategic_potential", "label": "Growth", "weight": 10},
        {"key": "security_and_reputational_integrity", "label": "Security", "weight": 10},
    ],
}
STAMP = "2026-10-21T12:00:00Z"


class CriterionEvidenceTests(unittest.TestCase):
    def test_maps_candidates_to_all_six_criteria_without_scoring(self):
        prospect = {"records": [{"project_name": "Alpha", "chain": "base", "contract_address": "0xalpha",
                                 "identity_risk": {"identity_status": "unknown", "risk_status": "unknown"}}]}
        public = {"records": [{
            "project_name": "Alpha", "chain": "base", "contract_address": "0xalpha",
            "criterion_evidence_candidates": [
                {"criterion": "service_fit_and_demonstrated_need", "candidate_type": "liquidity_language", "observed": True, "evidence_url": "https://alpha.example", "observed_at": STAMP},
                {"criterion": "market_activity_and_commercial_potential", "candidate_type": "market_metrics", "observed": True, "evidence_url": "https://dexscreener.com/token/alpha", "observed_at": STAMP, "metrics": {"volume_24h_usd": 1000}},
                {"criterion": "buying_trigger_and_timing", "candidate_type": "undated_homepage_trigger_keyword_match", "observed": True, "evidence_url": "https://alpha.example", "observed_at": STAMP},
                {"criterion": "project_credibility_and_team_access", "candidate_type": "contract_mentioned", "observed": True, "evidence_url": "https://alpha.example", "observed_at": STAMP},
                {"criterion": "growth_and_strategic_potential", "candidate_type": "roadmap_language", "observed": True, "evidence_url": "https://alpha.example", "observed_at": STAMP},
            ],
        }]}
        security = {"records": [{"project_name": "Alpha", "chain": "base", "contract_address": "0xalpha",
                                 "provider": "GoPlus", "provider_url": "https://api.example/security",
                                 "observed_at": STAMP, "fetch_status": "success", "provider_report_status": "found",
                                 "risk_status": "no_high_risk_flag_detected_by_provider", "findings": [],
                                 "criterion_evidence_candidate": {"criterion": "security_and_reputational_integrity", "status": "candidate_only", "evidence_url": "https://api.example/security", "observed_at": STAMP}}]}
        trigger = {"records": [{"project_name": "Alpha", "chain": "base", "contract_address": "0xalpha",
                                "trigger_candidates": [{"trigger_type": "exchange_listing", "status": "candidate_only",
                                                        "event_url": "https://news.example/alpha", "published_at": STAMP,
                                                        "observed_at": STAMP, "title": "Alpha listing"}]}]}
        result = build_criterion_evidence(prospect, CRITERIA, public, security, trigger, STAMP)
        row = result["records"][0]
        self.assertEqual(len(row["criteria"]), 6)
        self.assertEqual({item["key"] for item in row["criteria"]}, {item["key"] for item in CRITERIA["criteria"]})
        self.assertTrue(all(item["assessment_status"] == "unknown" for item in row["criteria"]))
        self.assertTrue(all(item["evidence_coverage_eligible"] is False for item in row["criteria"]))
        self.assertEqual(row["qualification_score"], None)
        self.assertEqual(row["score_status"], "withheld")
        self.assertEqual(result["records_with_scores"], 0)
        trigger_row = next(item for item in row["criteria"] if item["key"] == "buying_trigger_and_timing")
        self.assertEqual(trigger_row["candidate_evidence_count"], 1)
        self.assertFalse(result["canonical_criterion_reviews_changed"])
        self.assertFalse(result["outreach_enabled"])

    def test_no_source_evidence_preserves_unknown_not_absent(self):
        prospect = {"records": [{"project_name": "Beta", "chain": "solana", "contract_address": "So111"}]}
        result = build_criterion_evidence(prospect, CRITERIA, {"records": []}, {"records": []}, {"records": []}, STAMP)
        self.assertTrue(all(item["assessment_status"] == "unknown" for item in result["records"][0]["criteria"]))
        self.assertTrue(all(item["candidate_evidence_status"] == "unknown" for item in result["records"][0]["criteria"]))
        self.assertEqual(result["records_with_scores"], 0)


if __name__ == "__main__":
    unittest.main()
