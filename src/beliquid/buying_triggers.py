"""Human-reviewed, evidence-backed buying-trigger records.

This module validates reviewer-supplied findings; it does not scrape news or
infer buying intent from market metrics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlparse

TriggerStatus = Literal["unknown", "inferred", "verified"]
TRIGGER_TYPES = {
    "exchange_listing",
    "new_trading_pair",
    "token_launch_or_tge",
    "venue_expansion",
    "documented_liquidity_issue",
    "milestone_or_campaign",
    "token_unlock",
    "other",
}
DEFAULT_REVIEWS_PATH = Path(__file__).resolve().parents[2] / "config" / "buying_trigger_reviews.json"


def _validate_evidence(url: str | None, observed_at: str | None) -> None:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("non-unknown buying trigger requires an evidence URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("buying trigger evidence URL must be an absolute HTTP(S) URL")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ValueError("non-unknown buying trigger requires an observation timestamp")
    try:
        parsed_time = datetime.fromisoformat(observed_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("buying trigger timestamp must be ISO 8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ValueError("buying trigger timestamp must include a timezone")


@dataclass(frozen=True, slots=True)
class BuyingTrigger:
    """One human-reviewed event; verified means the reviewer checked the cited source."""

    trigger_type: str = "other"
    status: TriggerStatus = "unknown"
    evidence_url: str | None = None
    observed_at: str | None = None
    event_date: str | None = None
    summary: str | None = None
    reviewer_note: str | None = None

    def __post_init__(self) -> None:
        if self.trigger_type not in TRIGGER_TYPES:
            raise ValueError(f"trigger_type must be one of: {', '.join(sorted(TRIGGER_TYPES))}")
        if self.status not in {"unknown", "inferred", "verified"}:
            raise ValueError("buying trigger status must be unknown, inferred, or verified")
        if self.status != "unknown":
            _validate_evidence(self.evidence_url, self.observed_at)
            if not isinstance(self.summary, str) or not self.summary.strip():
                raise ValueError("non-unknown buying trigger requires a concise summary")
        elif self.evidence_url is not None or self.observed_at is not None:
            _validate_evidence(self.evidence_url, self.observed_at)
        if self.event_date is not None:
            if not isinstance(self.event_date, str):
                raise ValueError("event_date must be an ISO 8601 calendar date")
            try:
                date.fromisoformat(self.event_date)
            except ValueError as exc:
                raise ValueError("event_date must be an ISO 8601 calendar date") from exc
        for field_name in ("summary", "reviewer_note"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{field_name} must be a string")
                object.__setattr__(self, field_name, value.strip() or None)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "trigger_type": self.trigger_type,
            "status": self.status,
            "evidence_url": self.evidence_url,
            "observed_at": self.observed_at,
            "event_date": self.event_date,
            "summary": self.summary,
            "reviewer_note": self.reviewer_note,
        }


@dataclass(frozen=True, slots=True)
class BuyingTriggerAssessment:
    """Zero or more human-reviewed trigger observations for one prospect."""

    triggers: tuple[BuyingTrigger, ...] = ()

    @property
    def status(self) -> TriggerStatus:
        if any(item.status == "verified" for item in self.triggers):
            return "verified"
        if any(item.status == "inferred" for item in self.triggers):
            return "inferred"
        return "unknown"

    @property
    def verified_count(self) -> int:
        return sum(item.status == "verified" for item in self.triggers)

    @property
    def inferred_count(self) -> int:
        return sum(item.status == "inferred" for item in self.triggers)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "trigger_count": len(self.triggers),
            "verified_count": self.verified_count,
            "inferred_count": self.inferred_count,
            "triggers": [item.to_dict() for item in self.triggers],
            "buying_intent_confirmed_by_market_metrics": False,
        }


def prospect_review_key(chain: str, contract_address: str | None) -> str:
    if not chain or not chain.strip() or not contract_address or not contract_address.strip():
        raise ValueError("chain and contract address are required for buying-trigger review matching")
    return f"{chain.strip().casefold()}:{contract_address.strip().casefold()}"


def load_buying_trigger_reviews(
    path: Path = DEFAULT_REVIEWS_PATH,
) -> dict[str, BuyingTriggerAssessment]:
    """Load reviewer records; malformed files fail closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load buying-trigger review records: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("reviews"), dict):
        raise ValueError("buying-trigger review file must contain a 'reviews' object")
    result: dict[str, BuyingTriggerAssessment] = {}
    allowed = {"trigger_type", "status", "evidence_url", "observed_at", "event_date", "summary", "reviewer_note"}
    for raw_key, raw_review in payload["reviews"].items():
        if not isinstance(raw_key, str) or ":" not in raw_key or not isinstance(raw_review, list):
            raise ValueError("each buying-trigger review must use a 'chain:contract' key and a list of triggers")
        key = raw_key.strip().casefold()
        if not key or key in result:
            raise ValueError(f"duplicate or empty buying-trigger review key: {raw_key!r}")
        triggers = []
        for raw_trigger in raw_review:
            if not isinstance(raw_trigger, dict):
                raise ValueError(f"each buying-trigger entry for {raw_key!r} must be an object")
            unexpected = set(raw_trigger) - allowed
            if unexpected:
                raise ValueError(f"unsupported buying-trigger fields for {raw_key!r}: {', '.join(sorted(unexpected))}")
            try:
                triggers.append(BuyingTrigger(**raw_trigger))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid buying-trigger review for {raw_key!r}: {exc}") from exc
        result[key] = BuyingTriggerAssessment(tuple(triggers))
    return result


def assessment_for_prospect(
    chain: str,
    contract_address: str | None,
    reviews: Mapping[str, BuyingTriggerAssessment],
) -> BuyingTriggerAssessment:
    if not contract_address:
        return BuyingTriggerAssessment()
    return reviews.get(prospect_review_key(chain, contract_address), BuyingTriggerAssessment())
