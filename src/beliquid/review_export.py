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
from beliquid.buying_triggers import (
    assessment_for_prospect as trigger_assessment_for_prospect,
    load_buying_trigger_reviews,
    DEFAULT_REVIEWS_PATH as DEFAULT_TRIGGER_REVIEWS_PATH,
)
from beliquid.models import ProspectRecord
from beliquid.market_priority import prioritize_market_research
from beliquid.qualification import load_criteria_config, qualify_discovered_record
from beliquid.criterion_reviews import (
    assessments_for_prospect,
    load_criterion_reviews,
    DEFAULT_REVIEWS_PATH as DEFAULT_CRITERION_REVIEWS_PATH,
)


def _record_dict(
    record: ProspectRecord,
    config: dict[str, Any],
    identity_risk_reviews: dict[str, Any],
    buying_trigger_reviews: dict[str, Any],
    criterion_reviews: dict[str, Any],
) -> dict[str, Any]:
    reviewed_criteria = assessments_for_prospect(record.chain, record.contract_address, criterion_reviews)
    qualification = qualify_discovered_record(record, config, reviewed_criteria)
    for criterion_report in qualification.get("criteria", []):
        criterion_key = criterion_report.get("criterion")
        review = reviewed_criteria.get(criterion_key, {})
        criterion_report["reviewer_note"] = review.get("note")
        criterion_report["reviewer_review_flag"] = review.get("review_flag")
    identity_risk = assessment_for_prospect(record.chain, record.contract_address, identity_risk_reviews)
    buying_triggers = trigger_assessment_for_prospect(record.chain, record.contract_address, buying_trigger_reviews)
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
        "buying_triggers": buying_triggers.to_dict(),
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
    buying_trigger_reviews_path: str | Path = DEFAULT_TRIGGER_REVIEWS_PATH,
    criterion_reviews_path: str | Path = DEFAULT_CRITERION_REVIEWS_PATH,
) -> dict[str, str]:
    """Write full-batch exports with reviewer-managed criterion, identity, risk, and trigger findings."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    config = load_criteria_config()
    identity_risk_reviews = load_identity_risk_reviews(Path(identity_risk_reviews_path))
    buying_trigger_reviews = load_buying_trigger_reviews(Path(buying_trigger_reviews_path))
    criterion_reviews = load_criterion_reviews(Path(criterion_reviews_path), config)
    rows = [
        _record_dict(record, config, identity_risk_reviews, buying_trigger_reviews, criterion_reviews)
        for record in records
    ]

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

    trigger_status_counts: dict[str, int] = {}
    trigger_total = 0
    verified_trigger_total = 0
    inferred_trigger_total = 0
    for row in rows:
        trigger_data = row["buying_triggers"]
        status = trigger_data["status"]
        trigger_status_counts[status] = trigger_status_counts.get(status, 0) + 1
        trigger_total += trigger_data["trigger_count"]
        verified_trigger_total += trigger_data["verified_count"]
        inferred_trigger_total += trigger_data["inferred_count"]
    buying_trigger_summary = {
        "review_records_loaded": len(buying_trigger_reviews),
        "prospects_exported": len(rows),
        "prospects_by_status": trigger_status_counts,
        "trigger_observations": trigger_total,
        "verified_trigger_observations": verified_trigger_total,
        "inferred_trigger_observations": inferred_trigger_total,
        "buying_intent_verified_by_market_metrics": False,
        "automated_trigger_discovery_enabled": False,
    }
    summary["buying_triggers"] = buying_trigger_summary

    criterion_review_summary = {
        "review_records_loaded": len(criterion_reviews),
        "prospects_exported": len(rows),
        "prospects_with_any_criterion_review": sum(
            any(item["status"] != "unknown" for item in row["qualification"]["criteria"])
            for row in rows
        ),
        "scores_issued": sum(row["qualification"]["score_percent"] is not None for row in rows),
        "scores_withheld": sum(row["qualification"]["score_percent"] is None for row in rows),
        "minimum_evidence_coverage_percent": config["minimum_evidence_coverage_percent"],
    }
    summary["criterion_reviews"] = criterion_review_summary

    json_path = destination / "prospect-review.json"
    csv_path = destination / "prospect-review.csv"
    batch_path = destination / "pipeline-summary.json"
    json_payload = {
        "schema_version": 7,
        "source": "DEX Screener",
        "records_exported": len(rows),
        "qualification_summary": summary.get("qualification", {}),
        "identity_risk_summary": identity_risk_summary,
        "market_research_priority_summary": market_priority_summary,
        "buying_trigger_summary": buying_trigger_summary,
        "criterion_review_summary": criterion_review_summary,
        "records": rows,
        "important_note": (
            "Research-only export. Market priority is an unvalidated research heuristic, not a lead score. "
            "Criterion findings remain unknown until criterion-specific evidence is reviewed. Identity/risk findings are loaded from config/identity_risk_reviews.json; "
            "adverse identity or risk findings route to manual_hold. Buying triggers are human-reviewed records from "
            "config/buying_trigger_reviews.json; trigger labels do not automatically alter scores or identity/risk routes. "
            "Market metrics alone do not verify buying intent. Criterion scores use only the reviewer-managed "
            "config/criterion_reviews.json assessments and remain withheld below the evidence-coverage threshold. "
            "No outreach is enabled."
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
        "buying_trigger_status", "buying_trigger_count", "verified_trigger_count",
        "inferred_trigger_count", "buying_triggers_json",
    ]
    fieldnames = [
        "project_name", "token_symbol", "chain", "contract_address",
        "website_url_candidate", "triage_bucket", *metric_keys, "market_research_priority", "market_priority_signals", "market_priority_reasons", "volume_to_liquidity_ratio", *identity_risk_fields,
        *[f"{key}_status" for key in criterion_keys],
        *[field for key in criterion_keys for field in (
            f"review_{key}_status", f"review_{key}_evidence_url",
            f"review_{key}_observed_at", f"review_{key}_reviewer_note",
            f"review_{key}_evidence_urls_json", f"review_{key}_evidence_timestamps_json",
            f"review_{key}_review_flag",
        )],
        "score_percent", "score_status", "evidence_coverage_percent", "outreach_enabled",
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
            buying_triggers = row["buying_triggers"]
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
                "buying_trigger_status": buying_triggers["status"],
                "buying_trigger_count": buying_triggers["trigger_count"],
                "verified_trigger_count": buying_triggers["verified_count"],
                "inferred_trigger_count": buying_triggers["inferred_count"],
                "buying_triggers_json": json.dumps(buying_triggers["triggers"], sort_keys=True),
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
            reviewed_criteria = assessments_for_prospect(
                row["chain"], row["contract_address"], criterion_reviews
            )
            for key in criterion_keys:
                review = reviewed_criteria.get(key, {})
                csv_row[f"review_{key}_status"] = review.get("status", "unknown")
                evidence_urls = review.get("evidence_urls", [])
                evidence_timestamps = review.get("evidence_timestamps", [])
                csv_row[f"review_{key}_evidence_url"] = ";".join(evidence_urls)
                csv_row[f"review_{key}_observed_at"] = ";".join(evidence_timestamps)
                csv_row[f"review_{key}_reviewer_note"] = review.get("note") or ""
                csv_row[f"review_{key}_evidence_urls_json"] = json.dumps(evidence_urls, ensure_ascii=False)
                csv_row[f"review_{key}_evidence_timestamps_json"] = json.dumps(evidence_timestamps, ensure_ascii=False)
                csv_row[f"review_{key}_review_flag"] = review.get("review_flag") or ""
            csv_row.update({
                "score_percent": qualification["score_percent"],
                "score_status": qualification["score_status"],
                "evidence_coverage_percent": qualification["evidence_coverage_percent"],
                "outreach_enabled": str(bool(qualification["outreach_enabled"])).lower(),
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
