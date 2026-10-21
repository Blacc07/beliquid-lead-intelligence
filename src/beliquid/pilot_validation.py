"""Generate a controlled pilot-validation report without changing reviewer findings.

Engineering integrity and prospect evidence quality are reported separately. Readiness
means a record is organized for a second human review; it is not approval or outreach
authorization.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

CRITERIA = (
    "service_fit_and_demonstrated_need",
    "market_activity_and_commercial_potential",
    "buying_trigger_and_timing",
    "project_credibility_and_team_access",
    "growth_and_strategic_potential",
    "security_and_reputational_integrity",
)


def assess_record(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("identity_risk") or {}
    qualification = record.get("qualification") or {}
    triggers = record.get("buying_triggers") or {}
    criteria = {
        item.get("criterion"): item
        for item in qualification.get("criteria", [])
        if isinstance(item, dict)
    }
    assessed = {
        key: criteria.get(key, {}).get("status", "unknown")
        for key in CRITERIA
    }
    confirmed = sum(status == "confirmed" for status in assessed.values())
    not_present = sum(status == "not_present" for status in assessed.values())
    unknown = sum(status == "unknown" for status in assessed.values())
    evidence_complete = all(
        assessed[key] != "unknown"
        and bool(criteria.get(key, {}).get("evidence_urls"))
        and len(criteria.get(key, {}).get("evidence_urls", []))
        == len(criteria.get(key, {}).get("evidence_timestamps", []))
        and bool(criteria.get(key, {}).get("evidence_timestamps"))
        for key in CRITERIA
    )
    flags = list(qualification.get("review_flags") or [])
    for item in criteria.values():
        flag = item.get("reviewer_review_flag")
        if flag:
            flags.append(str(flag))
    identity_status = identity.get("identity_status", "unknown")
    risk_status = identity.get("risk_status", "unknown")
    identity_clear = (
        identity_status == "verified"
        and risk_status == "clear"
        and bool(identity.get("identity_evidence_url"))
        and bool(identity.get("identity_observed_at"))
        and bool(identity.get("risk_evidence_url"))
        and bool(identity.get("risk_observed_at"))
    )
    has_activity = (
        confirmed > 0 or not_present > 0
        or identity_status != "unknown" or risk_status != "unknown"
        or int(triggers.get("trigger_count", 0) or 0) > 0
    )
    if identity_status == "mismatch" or risk_status == "concern" or record.get("action_route") == "manual_hold":
        completion = "blocked_manual_hold"
        readiness_reasons = ["Independent identity/risk hold requires human resolution."]
    elif evidence_complete and identity_clear and not flags:
        completion = "ready_for_second_review"
        readiness_reasons = ["All six criteria assessed with evidence; identity/risk evidence complete; no review flags."]
    elif has_activity:
        completion = "in_progress"
        readiness_reasons = []
        if not evidence_complete:
            readiness_reasons.append("One or more criteria remain unknown or lack paired evidence.")
        if not identity_clear:
            readiness_reasons.append("Identity and risk are not both verified/clear with evidence.")
        if flags:
            readiness_reasons.append("Review flags remain open.")
    else:
        completion = "not_started"
        readiness_reasons = ["No criterion, identity/risk, or trigger review has been recorded."]
    return {
        "project_name": record.get("project_name", ""),
        "token_symbol": record.get("token_symbol", ""),
        "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""),
        "action_route": record.get("action_route", "research"),
        "identity_status": identity_status,
        "risk_status": risk_status,
        "criteria_confirmed": confirmed,
        "criteria_not_present": not_present,
        "criteria_unknown": unknown,
        "criteria_evidence_complete": evidence_complete,
        "buying_trigger_status": triggers.get("status", "unknown"),
        "buying_trigger_count": int(triggers.get("trigger_count", 0) or 0),
        "score_status": qualification.get("score_status", "insufficient_evidence"),
        "score_percent": qualification.get("score_percent"),
        "evidence_coverage_percent": qualification.get("evidence_coverage_percent", 0),
        "review_flags": sorted(set(flags)),
        "review_completion_status": completion,
        "second_review_readiness_reasons": readiness_reasons,
        "outreach_enabled": False,
    }


def build_report(payload: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    records = payload.get("records", [])
    assessments = [assess_record(record) for record in records]
    counts: dict[str, int] = {}
    for item in assessments:
        status = item["review_completion_status"]
        counts[status] = counts.get(status, 0) + 1
    engineering = {
        "validation_status": (manifest or {}).get("validation", {}).get("validation_status", "not_available"),
        "records_validated": (manifest or {}).get("validation", {}).get("records_validated", 0),
        "csv_json_field_comparisons": (manifest or {}).get("validation", {}).get("csv_json_field_comparisons", 0),
        "unit_tests_are_reported_by_ci_separately": True,
        "interpretation": "Engineering checks establish structural integrity and export parity, not prospect evidence truth or commercial value.",
    }
    evidence_quality = {
        "records_in_batch": len(assessments),
        "criteria_confirmed": sum(item["criteria_confirmed"] for item in assessments),
        "criteria_not_present": sum(item["criteria_not_present"] for item in assessments),
        "criteria_unknown": sum(item["criteria_unknown"] for item in assessments),
        "records_with_all_six_criteria_assessed_and_evidenced": sum(item["criteria_evidence_complete"] for item in assessments),
        "review_completion_counts": counts,
        "scores_issued": sum(item["score_percent"] is not None for item in assessments),
        "scores_withheld": sum(item["score_percent"] is None for item in assessments),
        "outreach_enabled": False,
        "interpretation": "Review completion and evidence presence are process indicators, not proof that evidence is true, buying intent exists, or outreach is authorized.",
    }
    return {
        "report_schema_version": 1,
        "engineering_validation": engineering,
        "prospect_evidence_quality": evidence_quality,
        "records": assessments,
        "second_review_readiness_definition": (
            "All six criteria have non-unknown statuses and paired evidence URLs/timestamps; identity is verified; risk is clear; "
            "identity/risk evidence is present; and no review flags remain. This is a queueing recommendation only, not a second-review result."
        ),
        "important_note": "This report summarizes current exported reviewer data only. It does not modify statuses, infer missing facts, validate source truth, or enable outreach.",
    }


def write_report(artifacts_dir: Path) -> dict[str, str]:
    source = artifacts_dir / "prospect-review.json"
    if not source.is_file():
        raise ValueError(f"required batch artifact missing: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    manifest_path = artifacts_dir / "audit-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    report = build_report(payload, manifest)
    json_path = artifacts_dir / "pilot-validation.json"
    csv_path = artifacts_dir / "pilot-validation.csv"
    markdown_path = artifacts_dir / "pilot-validation.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = [
        "project_name", "token_symbol", "chain", "contract_address", "action_route",
        "identity_status", "risk_status", "criteria_confirmed", "criteria_not_present",
        "criteria_unknown", "criteria_evidence_complete", "buying_trigger_status",
        "buying_trigger_count", "score_status", "score_percent", "evidence_coverage_percent",
        "review_completion_status", "outreach_enabled", "review_flags",
        "second_review_readiness_reasons",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in report["records"]:
            row = dict(item)
            row["review_flags"] = ";".join(item["review_flags"])
            row["second_review_readiness_reasons"] = " | ".join(item["second_review_readiness_reasons"])
            writer.writerow(row)
    quality = report["prospect_evidence_quality"]
    engineering = report["engineering_validation"]
    lines = [
        "# Controlled pilot-validation report", "",
        "> Process report only. It does not establish source truth, buyer intent, commercial value, or outreach authorization.", "",
        "## Engineering validation (separate from prospect quality)", "",
        f"- Batch validation: **{engineering['validation_status']}**",
        f"- Records structurally validated: **{engineering['records_validated']}**",
        f"- CSV/JSON field comparisons: **{engineering['csv_json_field_comparisons']}**",
        "- Unit tests are reported separately in the GitHub Actions run.", "",
        "## Prospect evidence quality", "",
        f"- Records in batch: **{quality['records_in_batch']}**",
        f"- Criterion assessments: {quality['criteria_confirmed']} confirmed, {quality['criteria_not_present']} not present, {quality['criteria_unknown']} unknown",
        f"- Records with all six criteria assessed and evidenced: **{quality['records_with_all_six_criteria_assessed_and_evidenced']}**",
        f"- Scores issued / withheld: **{quality['scores_issued']} / {quality['scores_withheld']}**",
        f"- Outreach enabled: **{quality['outreach_enabled']}**", "",
        "### Review completion queue", "",
    ]
    for status in ("not_started", "in_progress", "ready_for_second_review", "blocked_manual_hold"):
        lines.append(f"- {status}: **{quality['review_completion_counts'].get(status, 0)}**")
    lines += ["", "## Record-level queue", "", "| Project | Chain | Contract | Route | Identity / risk | Criteria C / N / U | Coverage | Completion |", "|---|---|---|---|---|---:|---:|---|"]
    for item in report["records"]:
        lines.append(
            f"| {item['project_name']} | {item['chain']} | {item['contract_address']} | {item['action_route']} | "
            f"{item['identity_status']} / {item['risk_status']} | {item['criteria_confirmed']} / {item['criteria_not_present']} / {item['criteria_unknown']} | "
            f"{item['evidence_coverage_percent']}% | {item['review_completion_status']} |"
        )
    lines += ["", "## Interpretation", "", report["important_note"], "", report["second_review_readiness_definition"], ""]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    try:
        result = write_report(args.artifacts_dir)
        print(json.dumps({"report_status": "written", **result}, indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"report_status": "failed", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
