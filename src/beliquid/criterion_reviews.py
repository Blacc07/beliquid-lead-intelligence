"""Load and validate human-reviewed criterion assessments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from beliquid.scoring import SignalAssessment

DEFAULT_REVIEWS_PATH = Path(__file__).resolve().parents[2] / "config" / "criterion_reviews.json"
ALLOWED_STATUSES = {"unknown", "confirmed", "not_present"}
ALLOWED_FIELDS = {"criterion", "status", "evidence_urls", "evidence_timestamps", "note", "review_flag"}


def prospect_review_key(chain: str, contract_address: str | None) -> str:
    if not chain or not chain.strip() or not contract_address or not contract_address.strip():
        raise ValueError("chain and contract address are required for criterion review matching")
    return f"{chain.strip().casefold()}:{contract_address.strip().casefold()}"


def load_criterion_reviews(
    path: Path = DEFAULT_REVIEWS_PATH,
    criteria_config: dict | None = None,
) -> dict[str, dict[str, dict]]:
    """Return validated reviewer records keyed by normalized chain:contract and criterion."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load criterion review records: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("reviews"), dict):
        raise ValueError("criterion review file must contain a 'reviews' object")
    known_criteria = {item["key"] for item in criteria_config["criteria"]} if criteria_config else None
    result: dict[str, dict[str, dict]] = {}
    for raw_key, raw_criteria in payload["reviews"].items():
        if not isinstance(raw_key, str) or ":" not in raw_key or not isinstance(raw_criteria, dict):
            raise ValueError("each criterion review must use a 'chain:contract' key and an object of criteria")
        key = raw_key.strip().casefold()
        if not key or key in result:
            raise ValueError(f"duplicate or empty criterion review key: {raw_key!r}")
        clean: dict[str, dict] = {}
        for criterion, raw in raw_criteria.items():
            if not isinstance(criterion, str) or not isinstance(raw, dict):
                raise ValueError(f"criterion entries for {raw_key!r} must be criterion-keyed objects")
            if known_criteria is not None and criterion not in known_criteria:
                raise ValueError(f"unknown criterion {criterion!r} for {raw_key!r}")
            unexpected = set(raw) - (ALLOWED_FIELDS - {"criterion"})
            if unexpected:
                raise ValueError(f"unsupported fields for criterion {criterion!r}: {', '.join(sorted(unexpected))}")
            status = raw.get("status", "unknown")
            if not isinstance(status, str) or status not in ALLOWED_STATUSES:
                raise ValueError(f"invalid status for criterion {criterion!r}; expected unknown, confirmed, or not_present")
            urls = raw.get("evidence_urls", [])
            timestamps = raw.get("evidence_timestamps", [])
            if not isinstance(urls, list) or not isinstance(timestamps, list):
                raise ValueError(f"evidence_urls and evidence_timestamps must be lists for criterion {criterion!r}")
            note = raw.get("note")
            review_flag = raw.get("review_flag")
            if note is not None and not isinstance(note, str):
                raise ValueError(f"note must be a string for criterion {criterion!r}")
            if review_flag is not None and not isinstance(review_flag, str):
                raise ValueError(f"review_flag must be a string for criterion {criterion!r}")
            try:
                assessment = SignalAssessment(
                    key=criterion,
                    weight=1,
                    status=status,
                    evidence_urls=tuple(urls),
                    evidence_timestamps=tuple(timestamps),
                    note=note,
                    review_flag=review_flag,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid criterion review {raw_key!r}/{criterion}: {exc}") from exc
            clean[criterion] = {
                "status": assessment.status,
                "evidence_urls": list(assessment.evidence_urls),
                "evidence_timestamps": list(assessment.evidence_timestamps),
                "note": assessment.note,
                "review_flag": assessment.review_flag,
            }
        result[key] = clean
    return result


def assessments_for_prospect(
    chain: str,
    contract_address: str | None,
    reviews: Mapping[str, dict[str, dict]],
) -> dict[str, dict]:
    if not contract_address:
        return {}
    return reviews.get(prospect_review_key(chain, contract_address), {})
