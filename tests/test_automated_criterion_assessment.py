"""Tests for conservative, multi-source automated criterion assessment."""
import json
from pathlib import Path
import tempfile
import unittest

from beliquid.automated_criterion_assessment import assess_criterion_reviews
from beliquid.criterion_reviews import load_criterion_reviews


CRITERIA = {
    "minimum_evidence_coverage_percent": 60,
    "criteria": [
        {"key": "service_fit_and_demonstrated_need", "weight": 25},
        {"key": "market_activity_and_commercial_potential", "weight": 20},
        {"key": "buying_trigger_and_timing", "weight": 20},
        {"key": "project_credibility_and_team_access", "weight": 15},
        {"key": "growth_and_strategic_potential", "weight": 10},
        {"key": "security_and_reputational_integrity", "weight": 10},
    ],
}
STAMP1 = "2026-10-20T12:00:00Z"
STAMP2 = "2026-10-21T12:00:00Z"


class AutomatedCriterionAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.prospect = {"records": [{"project_name": "Alpha Protocol", "token_symbol": "ALPHA",
                                      "chain": "base", "contract_address": "0xabc123456789abcdef"}]}
        self.candidate1 = {"trigger_type": "exchange_listing", "status": "candidate_only",
            "provider": "CoinDesk", "source_scope": "global_news", "date_verified": True,
            "title": "Alpha Protocol ALPHA listing announced", "summary_excerpt": "ALPHA 0xabc123456789abcdef exchange listing",
            "event_url": "https://www.coindesk.com/news/alpha-listing", "published_at": STAMP1,
            "observed_at": STAMP1}
        self.candidate2 = {"trigger_type": "exchange_listing", "status": "candidate_only",
            "provider": "Cointelegraph", "source_scope": "global_news", "date_verified": True,
            "title": "Alpha Protocol ALPHA listing announced", "summary_excerpt": "ALPHA 0xabc123456789abcdef exchange listing",
            "event_url": "https://cointelegraph.com/news/alpha-listing", "published_at": STAMP2,
            "observed_at": STAMP2}

    def test_two_independent_dated_sources_confirm_only_buying_trigger_criterion(self):
        trigger = {"records": [{"project_name": "Alpha Protocol", "token_symbol": "ALPHA",
                                "chain": "base", "contract_address": "0xabc123456789abcdef",
                                "trigger_candidates": [self.candidate1, self.candidate2]}]}
        result = assess_criterion_reviews(self.prospect, trigger, CRITERIA, STAMP2)
        record = result["records"][0]
        trigger_review = result["criterion_reviews"]["reviews"]["base:0xabc123456789abcdef"]["buying_trigger_and_timing"]
        self.assertEqual(trigger_review["status"], "confirmed")
        self.assertEqual(len(trigger_review["evidence_urls"]), 2)
        self.assertEqual(record["criteria_assessed"], 1)
        self.assertEqual(record["score_coverage_percent"], 20)
        self.assertEqual(record["score_status"], "withheld_insufficient_evidence")
        self.assertEqual(result["criterion_weights"]["service_fit_and_demonstrated_need"], 25)
        self.assertFalse(result["outreach_enabled"])

    def test_generated_review_payload_passes_existing_review_schema(self):
        trigger = {"records": [{"chain": "base", "contract_address": "0xabc123456789abcdef",
                                "trigger_candidates": [self.candidate1, self.candidate2]}]}
        result = assess_criterion_reviews(self.prospect, trigger, CRITERIA, STAMP2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "automated-reviews.json"
            path.write_text(json.dumps(result["criterion_reviews"]), encoding="utf-8")
            loaded = load_criterion_reviews(path, CRITERIA)
        self.assertEqual(loaded["base:0xabc123456789abcdef"]["buying_trigger_and_timing"]["status"], "confirmed")

    def test_strong_identity_crosscheck_confirms_credibility_only(self):
        identity = {"records": [{"chain": "base", "contract_address": "0xabc123456789abcdef",
            "observed_at": STAMP2, "identity_candidate_assessment": {"status": "corroborated_candidate",
            "source_urls": ["https://alpha.example", "https://basescan.org/token/0xabc123456789abcdef",
                            "https://x.com/AlphaProtocol", "https://alpha.example/contact"]}}]}
        result = assess_criterion_reviews(self.prospect, {"records": []}, CRITERIA, STAMP2,
                                          identity_payload=identity)
        reviews = result["criterion_reviews"]["reviews"]["base:0xabc123456789abcdef"]
        self.assertEqual(reviews["project_credibility_and_team_access"]["status"], "confirmed")
        self.assertEqual(len(reviews["project_credibility_and_team_access"]["evidence_urls"]), 4)
        self.assertEqual(result["records"][0]["score_coverage_percent"], 15)
        self.assertEqual(result["records"][0]["score_status"], "withheld_insufficient_evidence")

    def test_single_source_does_not_confirm_criterion(self):
        trigger = {"records": [{"chain": "base", "contract_address": "0xabc123456789abcdef",
                                "trigger_candidates": [self.candidate1]}]}
        result = assess_criterion_reviews(self.prospect, trigger, CRITERIA, STAMP2)
        self.assertEqual(result["records"][0]["criteria_assessed"], 0)
        self.assertEqual(result["criterion_reviews"]["reviews"], {})

    def test_generic_project_name_match_does_not_confirm_unrelated_news(self):
        prospect = {"records": [{"project_name": "Launching", "token_symbol": "", "chain": "solana",
                                 "contract_address": "So11111111111111111111111111111111111111112"}]}
        candidates = [
            {**self.candidate1, "title": "Bybit listing announced", "summary_excerpt": "Bybit exchange listing"},
            {**self.candidate2, "title": "Bybit listing announced", "summary_excerpt": "Bybit exchange listing"},
        ]
        trigger = {"records": [{"chain": "solana", "contract_address": "So11111111111111111111111111111111111111112",
                                "trigger_candidates": candidates}]}
        result = assess_criterion_reviews(prospect, trigger, CRITERIA, STAMP2)
        self.assertEqual(result["records"][0]["criteria_assessed"], 0)

    def test_wrong_publisher_domain_is_not_accepted_as_independent_evidence(self):
        bad = {**self.candidate2, "event_url": "https://example.org/fake"}
        trigger = {"records": [{"chain": "base", "contract_address": "0xabc123456789abcdef",
                                "trigger_candidates": [self.candidate1, bad]}]}
        result = assess_criterion_reviews(self.prospect, trigger, CRITERIA, STAMP2)
        self.assertEqual(result["records"][0]["criteria_assessed"], 0)

    def test_no_evidence_never_becomes_not_present(self):
        result = assess_criterion_reviews(self.prospect, {"records": []}, CRITERIA, STAMP2)
        self.assertTrue(all(item["status"] == "unknown" for item in result["records"][0]["criteria"]))
        self.assertFalse(result["rules"]["negative_assessments_emitted"])


if __name__ == "__main__":
    unittest.main()
