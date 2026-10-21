"""Write a complete, human-reviewable prospect batch export."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from beliquid.identity_risk import (
    assessment_for_prospect,
    load_identity_risk_reviews,
    DEFAULT_REVIEWS_PATH,
)
from beliquid.models import ProspectRecord
from beliquid.market_priority import prioritize_market_research
from beliquid.qualification import load_criteria_config, qualify_discovered_record


def _record_dict(
    record: ProspectRecord,
    config: dict[str, Any],
    identity_risk_reviews: dict[str, Any],
) -> dict[str, Any]:
    qualification = qualify_discovered_record(record, config)
    identity_risk = assessment_for_prospect(record.chain, record.contract_address, identity_risk_reviews)
    market_research_priority = prioritize_market_research(dict(record.metrics))
    triage_bucket = (
        "identity_verification_required"
        if not record.website_url
        else "official_identity_check_required"
    )
    return {
        "project_name": record.project_name,
        "token_symbol": record.token_symbol,
        "chain": record.chain,
        "contract_address": record.contract_address,
        "website_url_candidate": record.website_url,
        "triage_bucket": triage_bucket,
        "identity_risk": identity_risk.to_dict(),
        "action_route": identity_risk.action_route,
        "market_research_priority": market_research_priority,
        "metrics": dict(record.metrics),
        "evidence": [
            {
                "source_name": item.source_name,
                "source_url": item.source_url,
                "observed_at": item.observed_at,
                "evidence_type": item.evidence_type,
                "notes": item.notes,
            }
            for item in record.evidence
        ],
        "qualification": qualification,
        "review_note": (
            "Research queue only. Candidate website is unverified; a DEX profile or market "
            "metric does not establish project identity, product activity, buying intent, or service fit. "
            "Identity/risk findings come only from the reviewer-managed input file. "
            "A documented identity mismatch or risk concern routes to manual_hold."
        ),
    }


def write_review_exports(
    records: list[ProspectRecord],
    summary: dict[str, Any],
    output_dir: str | Path = "artifacts",
    identity_risk_reviews_path: str | Path = DEFAULT_REVIEWS_PATH,
) -> dict[str, str]:
    """Write full-batch JSON and CSV exports using reviewer-managed risk findings."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    config = load_criteria_config()
    identity_risk_reviews = load_identity_risk_reviews(Path(identity_risk_reviews_path))
    rows = [_record_dict(record, config, identity_risk_reviews) for record in records]

    route_counts: dict[str, int] = {}
    for row in rows:
        route = row["action_route"]
        route_counts[route] = route_counts.get(route, 0) + 1
    identity_risk_summary = {
        "review_records_loaded": len(identity_risk_reviews),
        "prospects_exported": len(rows),
        "action_route_counts": route_counts,
        "manual_hold_count": route_counts.get("manual_hold", 0),
        "business_development_review_count": route_counts.get("business_development_review", 0),
        "research_count": route_counts.get("research", 0),
    }
    summary["identity_risk"] = identity_risk_summary
    priority_counts: dict[str, int] = {}
    for row in rows:
        priority = row["market_research_priority"]["priority"]
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
    market_priority_summary = {
        "priority_counts": priority_counts,
        "prospects_triaged": len(rows),
        "thresholds_are_pilot_heuristics": True,
        "qualification_scores_issued": 0,
        "buying_intent_verified_by_metrics": False,
    }
    summary["market_research_priority"] = market_priority_summary

    json_path = destination / "prospect-review.json"
    csv_path = destination / "prospect-review.csv"
    batch_path = destination / "pipeline-summary.json"
    json_payload = {
        "schema_version": 4,
        "source": "DEX Screener",
        "records_exported": len(rows),
        "qualification_summary": summary.get("qualification", {}),
        "identity_risk_summary": identity_risk_summary,
        "market_research_priority_summary": market_priority_summary,
        "records": rows,
        "important_note": (
            "Research-only export. Market priority is an unvalidated research heuristic, not a lead score. "
            "Criterion findings remain unknown until criterion-specific evidence is reviewed. Identity/risk findings are loaded from config/identity_risk_reviews.json; "
            "adverse identity or risk findings route to manual_hold. No outreach is enabled."
        ),
    }
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    batch_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    metric_keys = (
        "price_usd", "liquidity_usd", "volume_24h_usd", "market_cap_usd",
        "fdv_usd", "txns_24h_buys", "txns_24h_sells", "pool_count",
    )
    criterion_keys = [item["key"] for item in config["criteria"]]
    identity_risk_fields = [
        "identity_status", "identity_evidence_url", "identity_observed_at",
        "risk_status", "risk_evidence_url", "risk_observed_at", "action_route",
        "identity_risk_flags", "identity_risk_reviewer_note",
    ]
    fieldnames = [
        "project_name", "token_symbol", "chain", "contract_address",
        "website_url_candidate", "triage_bucket", *metric_keys, "market_research_priority", "market_priority_signals", "market_priority_reasons", "volume_to_liquidity_ratio", *identity_risk_fields,
        *[f"{key}_status" for key in criterion_keys],
        *[field for key in criterion_keys for field in (
            f"review_{key}_status", f"review_{key}_evidence_url",
            f"review_{key}_observed_at", f"review_{key}_reviewer_note",
        )],
        "score_percent", "score_status", "evidence_coverage_percent",
        "review_flags", "evidence_json", "review_note",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            qualification = row["qualification"]
            criteria_report = qualification.get("criteria", [])
            if not isinstance(criteria_report, list):
                criteria_report = []
            statuses = {}
            for item in criteria_report:
                if not isinstance(item, dict):
                    continue
                criterion_key = item.get("criterion", item.get("key"))
                if isinstance(criterion_key, str) and criterion_key:
                    statuses[criterion_key] = item.get("status", "unknown")
            identity_risk = row["identity_risk"]
            csv_row: dict[str, Any] = {
                key: row.get(key) for key in (
                    "project_name", "token_symbol", "chain", "contract_address",
                    "website_url_candidate", "triage_bucket", "review_note",
                )
            }
            csv_row.update(row["metrics"])
            priority = row["market_research_priority"]
            csv_row.update({
                "market_research_priority": priority["priority"],
                "market_priority_signals": ";".join(priority["signals"]),
                "market_priority_reasons": " | ".join(priority["reasons"]),
                "volume_to_liquidity_ratio": priority["volume_to_liquidity_ratio"],
            })
            csv_row.update({
                "identity_status": identity_risk["identity_status"],
                "identity_evidence_url": identity_risk["identity_evidence_url"] or "",
                "identity_observed_at": identity_risk["identity_observed_at"] or "",
                "risk_status": identity_risk["risk_status"],
                "risk_evidence_url": identity_risk["risk_evidence_url"] or "",
                "risk_observed_at": identity_risk["risk_observed_at"] or "",
                "action_route": identity_risk["action_route"],
                "identity_risk_flags": ";".join(identity_risk["review_flags"]),
                "identity_risk_reviewer_note": identity_risk["reviewer_note"] or "",
            })
            csv_row.update({f"{key}_status": statuses.get(key, "unknown") for key in criterion_keys})
            for key in criterion_keys:
                csv_row[f"review_{key}_status"] = "unknown"
                csv_row[f"review_{key}_evidence_url"] = ""
                csv_row[f"review_{key}_observed_at"] = ""
                csv_row[f"review_{key}_reviewer_note"] = ""
            csv_row.update({
                "score_percent": qualification["score_percent"],
                "score_status": qualification["score_status"],
                "evidence_coverage_percent": qualification["evidence_coverage_percent"],
                "review_flags": ";".join(qualification["review_flags"]),
                "evidence_json": json.dumps(row["evidence"], sort_keys=True),
            })
            writer.writerow(csv_row)

    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "summary": str(batch_path),
        "records_exported": str(len(rows)),
    }
