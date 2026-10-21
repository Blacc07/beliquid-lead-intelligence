"""Offline tests for evidence-backed identity and risk routing."""
import unittest

from beliquid.identity_risk import IdentityRiskAssessment


URL = "https://project.example/security-or-identity"
TIMESTAMP = "2026-10-21T12:00:00Z"


class IdentityRiskAssessmentTests(unittest.TestCase):
    def test_unknown_defaults_to_research_not_safe_or_qualified(self):
        assessment = IdentityRiskAssessment()
        self.assertEqual(assessment.action_route, "research")
        self.assertEqual(assessment.identity_status, "unknown")
        self.assertEqual(assessment.risk_status, "unknown")
        self.assertIn("official_identity_unverified", assessment.review_flags)
        self.assertIn("risk_review_incomplete", assessment.review_flags)

    def test_identity_mismatch_forces_manual_hold(self):
        assessment = IdentityRiskAssessment(
            identity_status="mismatch",
            identity_evidence_url=URL,
            identity_observed_at=TIMESTAMP,
            risk_status="clear",
            risk_evidence_url=URL,
            risk_observed_at=TIMESTAMP,
        )
        self.assertEqual(assessment.action_route, "manual_hold")
        self.assertIn("conflicting_project_identity", assessment.review_flags)

    def test_risk_concern_forces_manual_hold_even_if_identity_verified(self):
        assessment = IdentityRiskAssessment(
            identity_status="verified",
            identity_evidence_url=URL,
            identity_observed_at=TIMESTAMP,
            risk_status="concern",
            risk_evidence_url=URL,
            risk_observed_at=TIMESTAMP,
        )
        self.assertEqual(assessment.action_route, "manual_hold")
        self.assertIn("independent_risk_concern", assessment.review_flags)

    def test_only_verified_identity_and_clear_risk_route_to_business_review(self):
        assessment = IdentityRiskAssessment(
            identity_status="verified",
            identity_evidence_url=URL,
            identity_observed_at=TIMESTAMP,
            risk_status="clear",
            risk_evidence_url=URL,
            risk_observed_at=TIMESTAMP,
        )
        self.assertEqual(assessment.action_route, "business_development_review")

    def test_verified_identity_requires_evidence_url_and_timestamp(self):
        with self.assertRaisesRegex(ValueError, "evidence URL"):
            IdentityRiskAssessment(identity_status="verified")

    def test_clear_risk_requires_evidence_url_and_timestamp(self):
        with self.assertRaisesRegex(ValueError, "evidence URL"):
            IdentityRiskAssessment(risk_status="clear")

    def test_evidence_timestamp_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            IdentityRiskAssessment(
                identity_status="verified",
                identity_evidence_url=URL,
                identity_observed_at="2026-10-21T12:00:00",
            )

    def test_invalid_evidence_scheme_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            IdentityRiskAssessment(
                identity_status="mismatch",
                identity_evidence_url="javascript:alert(1)",
                identity_observed_at=TIMESTAMP,
            )


if __name__ == "__main__":
    unittest.main()
