"""Write a complete, human-reviewable prospect batch export.

Exports are workflow artifacts, not a permanent database. No qualification evidence
is inferred from discovery or market metrics, and all scores remain governed by
the qualification module.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from beliquid.models import ProspectRecord
from beliquid.qualification import load_criteria_config, qualify_discovered_record


def _record_dict(record: ProspectRecord, config: dict[str, Any]) -> dict[str, Any]:
    qualification = qualify_discovered_record(record, config)
    has_website = bool(record.website_url)
    # These are research queues, not qualification judgments or exclusions.
    triage_bucket = (
        "identity_verification_required"
        if not has_website
        else "official_identity_check_required"
    )
    return {
        "project_name": record.project_name,
        "token_symbol": record.token_symbol,
        "chain": record.chain,
        "contract_address": record.contract_address,
        "website_url_candidate": record.website_url,
        "triage_bucket": triage_bucket,
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
            "metric does not establish project identity, product activity, buying intent, or service fit."
        ),
    }


def write_review_exports(
    records: list[ProspectRecord],
    summary: dict[str, Any],
    output_dir: str | Path = "artifacts",
) -> dict[str, str]:
    """Write full-batch JSON and CSV files, returning their relative paths."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    config = load_criteria_config()
    rows = [_record_dict(record, config) for record in records]

    json_path = destination / "prospect-review.json"
    csv_path = destination / "prospect-review.csv"
    batch_path = destination / "pipeline-summary.json"

    json_payload = {
        "schema_version": 1,
        "source": "DEX Screener",
        "records_exported": len(rows),
        "qualification_summary": summary.get("qualification", {}),
        "records": rows,
        "important_note": (
            "Research-only export. Criterion findings remain unknown until a reviewer records "
            "criterion-specific evidence, URLs, timestamps, and notes. No outreach is enabled."
        ),
    }
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    batch_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    metric_keys = (
        "price_usd", "liquidity_usd", "volume_24h_usd", "market_cap_usd",
        "fdv_usd", "txns_24h_buys", "txns_24h_sells", "pool_count",
    )
    criterion_keys = [item["key"] for item in config["criteria"]]
    fieldnames = [
        "project_name", "token_symbol", "chain", "contract_address",
        "website_url_candidate", "triage_bucket", *metric_keys,
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
            statuses = {item["key"]: item["status"] for item in qualification["criteria"]}
            csv_row: dict[str, Any] = {
                key: row.get(key) for key in (
                    "project_name", "token_symbol", "chain", "contract_address",
                    "website_url_candidate", "triage_bucket", "review_note",
                )
            }
            csv_row.update(row["metrics"])
            csv_row.update({f"{key}_status": statuses.get(key, "unknown") for key in criterion_keys})
            # Reviewer fields are intentionally blank/unknown; exports do not invent findings.
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
