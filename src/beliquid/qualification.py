"""Configuration validation and conservative qualification of discovered prospects.

Discovery and market data are not criterion evidence. Until an evidence-review
adapter or human reviewer supplies criterion-level findings, every criterion
remains unknown and no score is issued.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from beliquid.models import ProspectRecord
from beliquid.scoring import SignalAssessment, score_lead

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "qualification_criteria.json"
REQUIRED_RULES = (
    "unknown_is_not_zero",
    "market_metrics_alone_are_not_buying_intent",
    "promotion_or_boosting_is_not_a_quality_signal",
    "confirmed_or_not_present_requires_evidence_url",
    "risk_flags_are_independent_of_score",
    "no_automated_outreach",
    "criterion_evidence_requires_url_and_timestamp",
    "discovery_and_market_data_do_not_auto_assess_criteria",
    "manual_sample_validation_required_before_prioritization",
)


def load_criteria_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load and strictly validate the qualification config before scoring."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load qualification criteria config: {exc}") from exc
    criteria = config.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("qualification config must contain a non-empty criteria list")
    keys = [item.get("key") for item in criteria if isinstance(item, dict)]
    if len(keys) != len(criteria) or any(not isinstance(key, str) or not key.strip() for key in keys):
        raise ValueError("every criterion must have a non-empty key")
    if len({key.casefold() for key in keys}) != len(keys):
        raise ValueError("qualification criterion keys must be unique")
    weights = [item.get("weight") for item in criteria]
    if any(isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0 for weight in weights):
        raise ValueError("every criterion weight must be a positive number")
    if sum(weights) != 100:
        raise ValueError(f"qualification criterion weights must total 100, got {sum(weights)}")
    for item in criteria:
        if not item.get("label") or not item.get("positive_definition") or not item.get("unknown_when"):
            raise ValueError(f"criterion {item['key']} is missing a definition")
    rules = config.get("rules", {})
    missing_rules = [key for key in REQUIRED_RULES if rules.get(key) is not True]
    if missing_rules:
        raise ValueError(f"required qualification safeguards are not enabled: {', '.join(missing_rules)}")
    threshold = config.get("minimum_evidence_coverage_percent")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 100:
        raise ValueError("minimum evidence coverage must be between 0 and 100")
    return config


def qualify_discovered_record(
    record: ProspectRecord,
    config: dict[str, Any],
    criterion_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score only explicit human assessments; discovery and market metrics never auto-assess criteria."""
    criterion_reviews = criterion_reviews or {}
    known_keys = {item["key"] for item in config["criteria"]}
    unexpected = set(criterion_reviews) - known_keys
    if unexpected:
        raise ValueError(f"criterion reviews contain unknown keys: {', '.join(sorted(unexpected))}")
    assessments = []
    for item in config["criteria"]:
        reviewed = criterion_reviews.get(item["key"], {})
        status = reviewed.get("status", "unknown")
        evidence_urls = tuple(reviewed.get("evidence_urls", []))
        evidence_timestamps = tuple(reviewed.get("evidence_timestamps", []))
        note = reviewed.get("note")
        review_flag = reviewed.get("review_flag")
        if status == "unknown" and not note:
            note = "Not yet assessed against the criterion definition; discovery and market metrics are not sufficient evidence."
        assessments.append(SignalAssessment(
            key=item["key"],
            weight=item["weight"],
            status=status,
            evidence_urls=evidence_urls,
            evidence_timestamps=evidence_timestamps,
            note=note,
            review_flag=review_flag,
        ))
    result = score_lead(
        assessments,
        minimum_coverage_percent=float(config["minimum_evidence_coverage_percent"]),
    )
    flags = list(result.review_flags)
    # These are review prompts, not claims that a project is fraudulent or unsuitable.
    flags.extend(("official_identity_unverified", "unclear_service_fit", "manual_evidence_review_required"))
    return {
        "project_name": record.project_name,
        "chain": record.chain,
        "contract_address": record.contract_address,
        "score_percent": result.score_percent,
        "score_status": result.status,
        "evidence_coverage_percent": result.coverage_percent,
        "assessed_weight": result.assessed_weight,
        "total_weight": result.total_weight,
        "review_flags": flags,
        "criteria": list(result.breakdown),
        "discovery_evidence": [
            {
                "source_name": item.source_name,
                "source_url": item.source_url,
                "observed_at": item.observed_at,
                "evidence_type": item.evidence_type,
            }
            for item in record.evidence
        ],
        "outreach_enabled": False,
    }


def summarize_qualification(records: list[ProspectRecord], config: dict[str, Any]) -> dict[str, Any]:
    reports = [qualify_discovered_record(record, config) for record in records]
    return {
        "configuration_status": config["status"],
        "criteria_weights_total": sum(item["weight"] for item in config["criteria"]),
        "prospects_evaluated": len(reports),
        "scores_issued": sum(report["score_percent"] is not None for report in reports),
        "scores_withheld_insufficient_evidence": sum(report["score_status"] == "insufficient_evidence" for report in reports),
        "manual_evidence_review_required": len(reports),
        "outreach_enabled": False,
        "sample": reports[:5],
        "note": (
            "Scores are withheld because no criterion-level evidence has been reviewed yet. "
            "Discovery and market metrics are candidates/provenance only. Validate a manually reviewed sample "
            "before using scores to prioritize prospects."
        ),
    }
