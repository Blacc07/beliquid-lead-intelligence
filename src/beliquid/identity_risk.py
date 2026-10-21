"""Independent identity verification and risk routing for BeLiquid prospects.

This module does not verify projects automatically. It validates reviewer-supplied
findings and routes unresolved or adverse findings conservatively.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

IdentityStatus = Literal["unknown", "verified", "mismatch"]
RiskStatus = Literal["unknown", "clear", "concern"]
ActionRoute = Literal["research", "business_development_review", "manual_hold"]


def _validate_evidence(url: str | None, observed_at: str | None, label: str) -> None:
    if not url or not url.strip():
        raise ValueError(f"{label} requires an evidence URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} evidence URL must be an absolute HTTP(S) URL")
    if not observed_at or not observed_at.strip():
        raise ValueError(f"{label} requires an observation timestamp")
    try:
        parsed_time = datetime.fromisoformat(observed_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} timestamp must be ISO 8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ValueError(f"{label} timestamp must include a timezone")


@dataclass(frozen=True, slots=True)
class IdentityRiskAssessment:
    """Human-reviewed identity and risk states, independent from lead score."""

    identity_status: IdentityStatus = "unknown"
    identity_evidence_url: str | None = None
    identity_observed_at: str | None = None
    risk_status: RiskStatus = "unknown"
    risk_evidence_url: str | None = None
    risk_observed_at: str | None = None
    reviewer_note: str | None = None

    def __post_init__(self) -> None:
        if self.identity_status not in {"unknown", "verified", "mismatch"}:
            raise ValueError("identity_status must be unknown, verified, or mismatch")
        if self.risk_status not in {"unknown", "clear", "concern"}:
            raise ValueError("risk_status must be unknown, clear, or concern")
        if self.identity_status in {"verified", "mismatch"}:
            _validate_evidence(self.identity_evidence_url, self.identity_observed_at, "identity assessment")
        if self.risk_status in {"clear", "concern"}:
            _validate_evidence(self.risk_evidence_url, self.risk_observed_at, "risk assessment")
        if self.reviewer_note is not None:
            object.__setattr__(self, "reviewer_note", self.reviewer_note.strip() or None)

    @property
    def action_route(self) -> ActionRoute:
        """Adverse findings force a hold; unknowns remain in research."""
        if self.identity_status == "mismatch" or self.risk_status == "concern":
            return "manual_hold"
        if self.identity_status == "verified" and self.risk_status == "clear":
            return "business_development_review"
        return "research"

    @property
    def review_flags(self) -> tuple[str, ...]:
        flags: list[str] = []
        if self.identity_status == "unknown":
            flags.append("official_identity_unverified")
        elif self.identity_status == "mismatch":
            flags.append("conflicting_project_identity")
        if self.risk_status == "unknown":
            flags.append("risk_review_incomplete")
        elif self.risk_status == "concern":
            flags.append("independent_risk_concern")
        return tuple(flags)

    def to_dict(self) -> dict[str, str | None | list[str]]:
        return {
            "identity_status": self.identity_status,
            "identity_evidence_url": self.identity_evidence_url,
            "identity_observed_at": self.identity_observed_at,
            "risk_status": self.risk_status,
            "risk_evidence_url": self.risk_evidence_url,
            "risk_observed_at": self.risk_observed_at,
            "action_route": self.action_route,
            "review_flags": list(self.review_flags),
            "reviewer_note": self.reviewer_note,
        }
