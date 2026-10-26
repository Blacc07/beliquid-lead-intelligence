"""Deterministic, source-backed criterion assessments from corroborated public events.

Only narrowly defined positive assessments are emitted. Missing, conflicting, single-source,
or weakly matched evidence stays unknown; this module never emits not_present.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

ALLOWED_NEWS = {
    "CoinDesk": {"coindesk.com"},
    "Cointelegraph": {"cointelegraph.com"},
}
STOP_WORDS = {"the", "and", "for", "with", "from", "this", "that", "will", "has", "have", "its", "new", "token", "crypto", "project"}
TRIGGER_TERMS = ("listing", "listed", "launch", "mainnet", "tge", "token generation", "trading pair", "exchange")
GROWTH_TERMS = ("partnership", "integrat", "funding", "raised", "expansion", "mainnet", "launch", "product release")
SERVICE_TERMS = ("market maker", "market making", "liquidity provider", "liquidity issue", "shallow liquidity", "wide spread")


def _key(record: dict[str, Any]) -> str:
    return f"{str(record.get('chain') or '').strip().casefold()}:{str(record.get('contract_address') or '').strip().casefold()}"


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_event(candidate: dict[str, Any], prospect: dict[str, Any]) -> bool:
    provider = candidate.get("provider")
    if provider not in ALLOWED_NEWS:
        return False
    url = candidate.get("event_url")
    parsed = urlparse(url if isinstance(url, str) else "")
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.casefold().removeprefix("www.")
    if not any(host == domain or host.endswith("." + domain) for domain in ALLOWED_NEWS[provider]):
        return False
    if candidate.get("status") != "candidate_only" or not candidate.get("date_verified"):
        return False
    if _timestamp(candidate.get("published_at")) is None or _timestamp(candidate.get("observed_at")) is None:
        return False
    text = f"{candidate.get('title') or ''} {candidate.get('summary_excerpt') or ''}".casefold()
    name = str(prospect.get("project_name") or "").strip().casefold()
    symbol = str(prospect.get("token_symbol") or "").strip().casefold()
    contract = str(prospect.get("contract_address") or "").strip().casefold()
    # Require a strong entity match: contract address, or both project name and symbol.
    if contract and len(contract) >= 12 and contract in text:
        return True
    return bool(name and len(name) >= 4 and symbol and len(symbol) >= 2 and name in text and symbol in text)


def _title_tokens(candidate: dict[str, Any]) -> set[str]:
    title = str(candidate.get("title") or "").casefold()
    return {token for token in re.findall(r"[a-z0-9]{3,}", title) if token not in STOP_WORDS}


def _corroborated_pairs(candidates: list[dict[str, Any]], prospect: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    valid = [item for item in candidates if isinstance(item, dict) and _valid_event(item, prospect)]
    pairs = []
    for index, left in enumerate(valid):
        for right in valid[index + 1:]:
            if left.get("provider") == right.get("provider"):
                continue
            if left.get("trigger_type") != right.get("trigger_type"):
                continue
            left_date, right_date = _timestamp(left.get("published_at")), _timestamp(right.get("published_at"))
            if left_date is None or right_date is None or abs((left_date - right_date).total_seconds()) > 72 * 3600:
                continue
            left_tokens, right_tokens = _title_tokens(left), _title_tokens(right)
            union = left_tokens | right_tokens
            similarity = len(left_tokens & right_tokens) / len(union) if union else 0
            if similarity < 0.4:
                continue
            pairs.append((left, right))
    return pairs


def assess_criterion_reviews(prospect_payload: dict[str, Any], trigger_payload: dict[str, Any],
                             criteria_config: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    prospects = prospect_payload.get("records")
    trigger_records = trigger_payload.get("records")
    criteria = criteria_config.get("criteria")
    if not isinstance(prospects, list) or any(not isinstance(x, dict) for x in prospects):
        raise ValueError("prospect payload must contain a records list of objects")
    if not isinstance(trigger_records, list) or any(not isinstance(x, dict) for x in trigger_records):
        raise ValueError("trigger payload must contain a records list of objects")
    if not isinstance(criteria, list) or len(criteria) != 6 or sum(item.get("weight", 0) for item in criteria) != 100:
        raise ValueError("criteria configuration must preserve the six weighted criteria totaling 100")
    trigger_map = {_key(item): item for item in trigger_records}
    reviews: dict[str, dict[str, Any]] = {}
    reports = []
    for prospect in prospects:
        key = _key(prospect)
        trigger_record = trigger_map.get(key, {})
        candidates = trigger_record.get("trigger_candidates", [])
        if not isinstance(candidates, list):
            candidates = []
        pairs = _corroborated_pairs(candidates, prospect)
        criterion_reviews: dict[str, Any] = {}
        assessed = []
        for criterion in criteria:
            criterion_key = criterion["key"]
            status = "unknown"
            urls: list[str] = []
            timestamps: list[str] = []
            note = "No deterministic assessment rule was satisfied; criterion remains unknown."
            rule_id = None
            eligible_pairs = []
            for left, right in pairs:
                text = f"{left.get('title') or ''} {left.get('summary_excerpt') or ''} {right.get('title') or ''} {right.get('summary_excerpt') or ''}".casefold()
                if criterion_key == "buying_trigger_and_timing" and any(term in text for term in TRIGGER_TERMS):
                    eligible_pairs.append((left, right))
                    rule_id = "two_independent_dated_news_sources_same_trigger"
                elif criterion_key == "growth_and_strategic_potential" and any(term in text for term in GROWTH_TERMS):
                    eligible_pairs.append((left, right))
                    rule_id = "two_independent_dated_news_sources_same_growth_event"
                elif criterion_key == "service_fit_and_demonstrated_need" and any(term in text for term in SERVICE_TERMS):
                    eligible_pairs.append((left, right))
                    rule_id = "two_independent_dated_news_sources_explicit_liquidity_need"
            if eligible_pairs:
                left, right = eligible_pairs[0]
                status = "confirmed"
                urls = [left["event_url"], right["event_url"]]
                timestamps = [left["published_at"], right["published_at"]]
                note = ("Deterministic positive assessment: two distinct allowlisted news publishers reported a similar dated event "
                        "within 72 hours, with strong entity matching and overlapping title terms. This confirms only the cited "
                        "criterion evidence; it does not verify official identity, clear security risk, or authorize outreach.")
            if status != "unknown":
                criterion_reviews[criterion_key] = {
                    "status": status, "evidence_urls": urls, "evidence_timestamps": timestamps,
                    "note": note, "review_flag": None, "assessment_method": rule_id,
                }
            assessed.append({"key": criterion_key, "weight": criterion.get("weight"), "status": status,
                             "evidence_urls": urls, "evidence_timestamps": timestamps,
                             "assessment_method": rule_id if status != "unknown" else None, "note": note})
        if criterion_reviews:
            reviews[key] = criterion_reviews
        reports.append({"project_name": prospect.get("project_name", ""), "chain": prospect.get("chain", ""),
                        "contract_address": prospect.get("contract_address", ""), "prospect_key": key,
                        "criteria": assessed, "criteria_assessed": len(criterion_reviews),
                        "score_coverage_percent": sum(item["weight"] for item in assessed if item["status"] != "unknown"),
                        "score_status": "eligible_for_existing_scoring_threshold" if sum(item["weight"] for item in assessed if item["status"] != "unknown") >= criteria_config.get("minimum_evidence_coverage_percent", 60) else "withheld_insufficient_evidence",
                        "outreach_enabled": False})
    return {"schema_version": 1, "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "source": "deterministic corroboration of dated CoinDesk/Cointelegraph trigger candidates",
            "rules": {"independent_publishers_required": 2, "maximum_publication_time_delta_hours": 72,
                      "minimum_title_token_jaccard": 0.4, "entity_match": "exact contract or both project name and token symbol",
                      "negative_assessments_emitted": False, "absence_means_not_present": False},
            "criterion_weights": {item["key"]: item["weight"] for item in criteria},
            "minimum_evidence_coverage_percent": criteria_config.get("minimum_evidence_coverage_percent", 60),
            "records_exported": len(reports), "records_with_any_assessment": sum(bool(item["criteria_assessed"]) for item in reports),
            "criterion_reviews": {"schema_version": 1, "reviews": reviews},
            "scores_eligible_by_coverage": sum(item["score_status"] == "eligible_for_existing_scoring_threshold" for item in reports),
            "outreach_enabled": False, "records": reports,
            "note": "Only positive assessments supported by two independent, dated, allowlisted news sources are emitted. All other criteria stay unknown; no absence-based negative assessment is made."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--triggers", type=Path, default=Path("artifacts/trigger-research.json"))
    parser.add_argument("--criteria", type=Path, default=Path("config/qualification_criteria.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/automated-criterion-assessment.json"))
    parser.add_argument("--reviews-output", type=Path, default=Path("artifacts/automated-criterion-reviews.json"))
    args = parser.parse_args()
    try:
        result = assess_criterion_reviews(json.loads(args.input.read_text(encoding="utf-8")),
            json.loads(args.triggers.read_text(encoding="utf-8")), json.loads(args.criteria.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.reviews_output.write_text(json.dumps(result["criterion_reviews"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("records_exported", "records_with_any_assessment", "scores_eligible_by_coverage", "outreach_enabled")}, indent=2))
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
