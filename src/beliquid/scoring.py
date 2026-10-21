"""Explainable, evidence-backed lead scoring primitives.

This module deliberately does not infer commercial intent from token market metrics.
Callers must provide explicit signal assessments and evidence URLs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Literal
from urllib.parse import urlparse

SignalStatus = Literal["confirmed", "not_present", "unknown"]


@dataclass(frozen=True, slots=True)
class SignalAssessment:
    """One configurable scoring criterion with explicit evidence state."""

    key: str
    weight: float
    status: SignalStatus
    evidence_urls: tuple[str, ...] = ()
    evidence_timestamps: tuple[str, ...] = ()
    note: str | None = None
    review_flag: str | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("criterion key cannot be empty")
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
            raise ValueError("criterion weight must be numeric")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("criterion weight must be finite and greater than zero")
        if self.status not in {"confirmed", "not_present", "unknown"}:
            raise ValueError("status must be confirmed, not_present, or unknown")
        clean_urls: list[str] = []
        for value in self.evidence_urls:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("evidence URLs must be non-empty HTTP(S) URLs")
            parsed = urlparse(value.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("evidence URLs must be absolute HTTP(S) URLs")
            clean_urls.append(value.strip())
        timestamps = list(self.evidence_timestamps)
        if len(timestamps) != len(clean_urls):
            if clean_urls or timestamps:
                raise ValueError("each evidence URL must have exactly one evidence timestamp")
        for timestamp in timestamps:
            try:
                parsed_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise ValueError("evidence timestamps must be ISO 8601 timestamps") from exc
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                raise ValueError("evidence timestamps must include a timezone")
        if self.status in {"confirmed", "not_present"} and not clean_urls:
            raise ValueError("confirmed and not_present assessments require evidence URLs and timestamps")
        object.__setattr__(self, "key", self.key.strip())
        object.__setattr__(self, "evidence_urls", tuple(clean_urls))
        object.__setattr__(self, "evidence_timestamps", tuple(timestamps))
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip() or None)
        if self.review_flag is not None:
            object.__setattr__(self, "review_flag", self.review_flag.strip() or None)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Auditable score result; risk flags are independent of the numeric score."""

    earned_points: float
    assessed_weight: float
    total_weight: float
    coverage_percent: float
    score_percent: float | None
    status: str
    review_flags: tuple[str, ...]
    breakdown: tuple[dict[str, object], ...]


def score_lead(
    assessments: list[SignalAssessment],
    *,
    minimum_coverage_percent: float = 60.0,
) -> ScoreResult:
    """Score explicitly assessed criteria; unknown criteria are excluded from the denominator.

    score_percent is withheld when evidence coverage is below the configured
    threshold. It is a lead-fit score only when the caller supplies business-fit
    criteria; token market metrics alone should not be used as such criteria.
    """
    if not math.isfinite(minimum_coverage_percent) or not 0 <= minimum_coverage_percent <= 100:
        raise ValueError("minimum_coverage_percent must be between 0 and 100")

    seen: set[str] = set()
    for item in assessments:
        if item.key.casefold() in seen:
            raise ValueError(f"duplicate criterion key: {item.key}")
        seen.add(item.key.casefold())

    total_weight = sum(item.weight for item in assessments)
    assessed_weight = sum(item.weight for item in assessments if item.status != "unknown")
    earned_points = sum(item.weight for item in assessments if item.status == "confirmed")
    coverage = (assessed_weight / total_weight * 100.0) if total_weight else 0.0
    enough_evidence = assessed_weight > 0 and coverage >= minimum_coverage_percent
    score_percent = (earned_points / assessed_weight * 100.0) if enough_evidence else None

    if not assessments:
        status = "no_criteria"
    elif not enough_evidence:
        status = "insufficient_evidence"
    else:
        status = "scored"

    flags = tuple(dict.fromkeys(item.review_flag for item in assessments if item.review_flag))
    breakdown = tuple(
        {
            "criterion": item.key,
            "weight": item.weight,
            "status": item.status,
            "earned_points": item.weight if item.status == "confirmed" else 0.0 if item.status == "not_present" else None,
            "evidence_urls": list(item.evidence_urls),
            "evidence_timestamps": list(item.evidence_timestamps),
            "note": item.note,
            "review_flag": item.review_flag,
        }
        for item in assessments
    )
    return ScoreResult(
        earned_points=earned_points,
        assessed_weight=assessed_weight,
        total_weight=total_weight,
        coverage_percent=round(coverage, 2),
        score_percent=round(score_percent, 2) if score_percent is not None else None,
        status=status,
        review_flags=flags,
        breakdown=breakdown,
    )
