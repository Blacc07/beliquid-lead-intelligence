"""Independent identity verification and risk routing for BeLiquid prospects.

Findings are supplied by a human reviewer in config/identity_risk_reviews.json.
This module does not verify projects automatically; it validates reviewer findings
and routes unresolved or adverse findings conservatively.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlparse

IdentityStatus = Literal["unknown", "verified", "mismatch"]
RiskStatus = Literal["unknown", "clear", "concern"]
ActionRoute = Literal["research", "business_development_review", "manual_hold"]
DEFAULT_REVIEWS_PATH = Path(__file__).resolve().parents[2] / "config" / "identity_risk_reviews.json"


def _validate_evidence(url: str | None, observed_at: str | None, label: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"{label} requires an evidence URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} evidence URL must be an absolute HTTP(S) URL")
    if not isinstance(observed_at, str) or not observed_at.strip():
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
        if self.identity_status in {"verified", "mismatch"} or self.identity_evidence_url is not None or self.identity_observed_at is not None:
            _validate_evidence(self.identity_evidence_url, self.identity_observed_at, "identity assessment")
        if self.risk_status in {"clear", "concern"} or self.risk_evidence_url is not None or self.risk_observed_at is not None:
            _validate_evidence(self.risk_evidence_url, self.risk_observed_at, "risk assessment")
        if self.reviewer_note is not None:
            if not isinstance(self.reviewer_note, str):
                raise ValueError("reviewer_note must be a string")
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


def prospect_review_key(chain: str, contract_address: str | None) -> str:
    """Build a case-normalized chain/contract key for human review records."""
    if not chain or not chain.strip() or not contract_address or not contract_address.strip():
        raise ValueError("chain and contract address are required for identity/risk review matching")
    return f"{chain.strip().casefold()}:{contract_address.strip().casefold()}"


def load_identity_risk_reviews(
    path: Path = DEFAULT_REVIEWS_PATH,
) -> dict[str, IdentityRiskAssessment]:
    """Load reviewed findings; malformed files fail closed rather than being ignored."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load identity/risk review records: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("reviews"), dict):
        raise ValueError("identity/risk review file must contain a 'reviews' object")
    result: dict[str, IdentityRiskAssessment] = {}
    for raw_key, raw_review in payload["reviews"].items():
        if not isinstance(raw_key, str) or ":" not in raw_key or not isinstance(raw_review, dict):
            raise ValueError("each identity/risk review must use a 'chain:contract' key and an object value")
        key = raw_key.strip().casefold()
        if not key or key in result:
            raise ValueError(f"duplicate or empty identity/risk review key: {raw_key!r}")
        allowed = {
            "identity_status", "identity_evidence_url", "identity_observed_at",
            "risk_status", "risk_evidence_url", "risk_observed_at", "reviewer_note",
        }
        unexpected = set(raw_review) - allowed
        if unexpected:
            raise ValueError(f"unsupported fields for identity/risk review {raw_key!r}: {', '.join(sorted(unexpected))}")
        try:
            result[key] = IdentityRiskAssessment(**raw_review)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid identity/risk review for {raw_key!r}: {exc}") from exc
    return result


def assessment_for_prospect(
    chain: str,
    contract_address: str | None,
    reviews: Mapping[str, IdentityRiskAssessment],
) -> IdentityRiskAssessment:
    """Return the reviewed record for a prospect, or conservative unknown defaults."""
    if not contract_address:
        return IdentityRiskAssessment()
    return reviews.get(prospect_review_key(chain, contract_address), IdentityRiskAssessment())
