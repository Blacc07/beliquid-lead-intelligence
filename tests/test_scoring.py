"""Offline tests for explainable lead scoring."""

import unittest

from beliquid.scoring import SignalAssessment, score_lead


URL = "https://example.org/evidence"


class SignalAssessmentTests(unittest.TestCase):
    def test_requires_key_and_positive_finite_weight(self):
        for kwargs in (
            {"key": " ", "weight": 1, "status": "unknown"},
            {"key": "fit", "weight": 0, "status": "unknown"},
            {"key": "fit", "weight": float("nan"), "status": "unknown"},
            {"key": "fit", "weight": True, "status": "unknown"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SignalAssessment(**kwargs)

    def test_confirmed_and_not_present_require_evidence(self):
        for status in ("confirmed", "not_present"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                SignalAssessment("fit", 10, status)

    def test_rejects_invalid_evidence_url(self):
        with self.assertRaises(ValueError):
            SignalAssessment("fit", 10, "confirmed", ("javascript:alert(1)",))

    def test_unknown_can_have_no_evidence(self):
        assessment = SignalAssessment("fit", 10, "unknown")
        self.assertEqual(assessment.evidence_urls, ())


class ScoreLeadTests(unittest.TestCase):
    def test_scores_only_assessed_criteria_and_reports_coverage(self):
        result = score_lead([
            SignalAssessment("commercial_trigger", 40, "confirmed", (URL,)),
            SignalAssessment("official_site", 30, "not_present", (URL,)),
            SignalAssessment("funding_signal", 30, "unknown"),
        ])
        self.assertEqual(result.earned_points, 40)
        self.assertEqual(result.assessed_weight, 70)
        self.assertEqual(result.total_weight, 100)
        self.assertEqual(result.coverage_percent, 70)
        self.assertEqual(result.score_percent, 57.14)
        self.assertEqual(result.status, "scored")

    def test_withholds_score_when_evidence_coverage_is_too_low(self):
        result = score_lead([
            SignalAssessment("commercial_trigger", 20, "confirmed", (URL,)),
            SignalAssessment("official_site", 80, "unknown"),
        ])
        self.assertIsNone(result.score_percent)
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertEqual(result.coverage_percent, 20)

    def test_all_unknown_is_not_scored_as_zero(self):
        result = score_lead([SignalAssessment("commercial_trigger", 100, "unknown")])
        self.assertIsNone(result.score_percent)
        self.assertEqual(result.earned_points, 0)
        self.assertEqual(result.assessed_weight, 0)
        self.assertEqual(result.status, "insufficient_evidence")

    def test_review_flags_are_independent_of_score(self):
        result = score_lead([
            SignalAssessment("fit", 100, "confirmed", (URL,), review_flag="verify_project_identity"),
        ])
        self.assertEqual(result.score_percent, 100)
        self.assertEqual(result.review_flags, ("verify_project_identity",))

    def test_deduplicates_review_flags_in_order(self):
        result = score_lead([
            SignalAssessment("fit_a", 50, "confirmed", (URL,), review_flag="manual_review"),
            SignalAssessment("fit_b", 50, "not_present", (URL,), review_flag="manual_review"),
        ])
        self.assertEqual(result.review_flags, ("manual_review",))

    def test_rejects_duplicate_criterion_keys_case_insensitively(self):
        with self.assertRaises(ValueError):
            score_lead([
                SignalAssessment("Official_Site", 50, "unknown"),
                SignalAssessment("official_site", 50, "unknown"),
            ])

    def test_rejects_invalid_coverage_threshold(self):
        with self.assertRaises(ValueError):
            score_lead([], minimum_coverage_percent=101)

    def test_empty_assessments_have_no_criteria_status(self):
        result = score_lead([])
        self.assertEqual(result.status, "no_criteria")
        self.assertIsNone(result.score_percent)


if __name__ == "__main__":
    unittest.main()
