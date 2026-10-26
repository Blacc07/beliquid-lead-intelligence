"""Aggregate source-backed candidate evidence against the existing six criteria.

This is an evidence inventory, not a criterion assessment: candidate observations never
become confirmed/not-present reviews, scores, clearances, or outreach decisions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _key(record: dict[str, Any]) -> str:
    return f"{str(record.get('chain') or '').strip().casefold()}:{str(record.get('contract_address') or '').strip().casefold()}"


def _record_map(payload: Any, label: str) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{label} must contain a records list")
    result = {}
    for record in payload["records"]:
        if not isinstance(record, dict):
            raise ValueError(f"{label} records must be objects")
        key = _key(record)
        if key in result:
            raise ValueError(f"duplicate {label} record: {key}")
        result[key] = record
    return result


def _valid_source_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _candidate(source: str, criterion: str, candidate_type: str, source_url: Any, observed_at: Any,
               observed: bool | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "criterion": criterion,
        "source": source,
        "candidate_type": candidate_type,
        "status": "candidate_only",
        "observed": observed,
        "source_url": source_url if _valid_source_url(source_url) else None,
        "observed_at": observed_at if isinstance(observed_at, str) else None,
        "details": details or {},
        "note": "Candidate evidence only; it does not confirm or rule out this criterion.",
    }


def build_criterion_evidence(
    prospect_payload: dict[str, Any],
    criteria_config: dict[str, Any],
    public_research: dict[str, Any] | None = None,
    security_research: dict[str, Any] | None = None,
    trigger_research: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    prospects = prospect_payload.get("records")
    criteria = criteria_config.get("criteria")
    if not isinstance(prospects, list) or any(not isinstance(r, dict) for r in prospects):
        raise ValueError("prospect review must contain a records list of objects")
    if not isinstance(criteria, list) or len(criteria) != 6:
        raise ValueError("qualification criteria must define exactly six criteria")
    public_map = _record_map(public_research, "public research")
    security_map = _record_map(security_research, "security research")
    trigger_map = _record_map(trigger_research, "trigger research")
    now = generated_at or datetime.now(timezone.utc).isoformat()
    criterion_defs = {item["key"]: item for item in criteria if isinstance(item, dict) and item.get("key")}
    expected = {
        "service_fit_and_demonstrated_need",
        "market_activity_and_commercial_potential",
        "buying_trigger_and_timing",
        "project_credibility_and_team_access",
        "growth_and_strategic_potential",
        "security_and_reputational_integrity",
    }
    if set(criterion_defs) != expected:
        raise ValueError("qualification criterion keys do not match the supported six-criterion model")

    output_records = []
    for prospect in prospects:
        key = _key(prospect)
        public = public_map.get(key, {})
        security = security_map.get(key, {})
        trigger = trigger_map.get(key, {})
        evidence: dict[str, list[dict[str, Any]]] = {name: [] for name in expected}
        checks: dict[str, list[dict[str, Any]]] = {name: [] for name in expected}

        for item in public.get("criterion_evidence_candidates", []) if isinstance(public.get("criterion_evidence_candidates"), list) else []:
            if not isinstance(item, dict) or item.get("criterion") not in expected:
                continue
            candidate = _candidate(
                "candidate_project_page_or_market_feed",
                item["criterion"],
                str(item.get("candidate_type") or "source_observation"),
                item.get("evidence_url"),
                item.get("observed_at"),
                bool(item.get("observed")),
                {k: v for k, v in item.items() if k not in {"criterion", "candidate_type", "evidence_url", "observed_at", "observed", "status"}},
            )
            checks[item["criterion"]].append(candidate)
            if (item.get("observed") and candidate["source_url"] and candidate["observed_at"]
                    and not (item["criterion"] == "buying_trigger_and_timing" and item.get("candidate_type") == "undated_homepage_trigger_keyword_match")):
                evidence[item["criterion"]].append(candidate)

        security_candidate = security.get("criterion_evidence_candidate")
        if isinstance(security_candidate, dict):
            candidate = _candidate(
                str(security.get("provider") or "contract_security_provider"),
                "security_and_reputational_integrity",
                "provider_security_report",
                security_candidate.get("evidence_url") or security.get("provider_url"),
                security_candidate.get("observed_at") or security.get("observed_at"),
                security.get("fetch_status") == "success",
                {"fetch_status": security.get("fetch_status"), "provider_report_status": security.get("provider_report_status"),
                 "source_scoped_risk_status": security.get("risk_status"), "finding_count": len(security.get("findings", []))},
            )
            checks["security_and_reputational_integrity"].append(candidate)
            if security.get("fetch_status") == "success" and candidate["source_url"] and candidate["observed_at"]:
                evidence["security_and_reputational_integrity"].append(candidate)

        for candidate in trigger.get("trigger_candidates", []) if isinstance(trigger.get("trigger_candidates"), list) else []:
            if not isinstance(candidate, dict):
                continue
            source_url = candidate.get("event_url")
            observed_at = candidate.get("observed_at")
            item = _candidate("dated_project_or_news_feed", "buying_trigger_and_timing",
                              str(candidate.get("trigger_type") or "dated_event_candidate"),
                              source_url, observed_at, True,
                              {"title": candidate.get("title"), "published_at": candidate.get("published_at"),
                               "provider": candidate.get("provider"), "feed_url": candidate.get("feed_url"),
                               "status": candidate.get("status")})
            checks["buying_trigger_and_timing"].append(item)
            if candidate.get("status") == "candidate_only" and candidate.get("published_at") and item["source_url"] and item["observed_at"]:
                evidence["buying_trigger_and_timing"].append(item)

        qualification = prospect.get("qualification") if isinstance(prospect.get("qualification"), dict) else {}
        assessed_by_key = {
            item.get("criterion"): item for item in qualification.get("criteria", [])
            if isinstance(item, dict) and item.get("criterion")
        }
        criterion_rows = []
        for criterion_key in [item["key"] for item in criteria]:
            definition = criterion_defs[criterion_key]
            assessed = assessed_by_key.get(criterion_key, {})
            status = assessed.get("status", "unknown")
            urls = assessed.get("evidence_urls", [])
            timestamps = assessed.get("evidence_timestamps", [])
            assessment_evidence = [
                {"source_url": url, "observed_at": timestamps[index]}
                for index, url in enumerate(urls)
                if isinstance(url, str) and index < len(timestamps) and isinstance(timestamps[index], str)
            ]
            criterion_rows.append({
                "key": criterion_key,
                "label": definition.get("label", criterion_key),
                "weight": definition.get("weight"),
                "assessment_status": status,
                "candidate_evidence_status": "candidate_only" if evidence[criterion_key] else "unknown",
                "candidate_evidence_count": len(evidence[criterion_key]),
                "source_checks_count": len(checks[criterion_key]),
                "evidence_coverage_eligible": status in {"confirmed", "not_present"} and len(urls) > 0 and len(urls) == len(timestamps),
                "evidence": evidence[criterion_key],
                "assessed_evidence": assessment_evidence,
                "source_checks": checks[criterion_key],
                "note": assessed.get("reviewer_note") or assessed.get("note") or ("Unknown is preserved; absence of a candidate is not evidence of absence." if status == "unknown" else "Status is sourced from the validated criterion assessment used by the qualification pipeline."),
            })
        output_records.append({
            "project_name": prospect.get("project_name", ""),
            "chain": prospect.get("chain", ""),
            "contract_address": prospect.get("contract_address", ""),
            "prospect_key": key,
            "identity_status": (prospect.get("identity_risk") or {}).get("identity_status", "unknown"),
            "risk_status": (prospect.get("identity_risk") or {}).get("risk_status", "unknown"),
            "criteria": criterion_rows,
            "qualification_score": qualification.get("score_percent"),
            "score_status": qualification.get("score_status", "insufficient_evidence"),
            "outreach_enabled": False,
        })

    return {
        "schema_version": 1,
        "generated_at": now,
        "source": "aggregated public-page, market, trigger-feed, and contract-security candidate evidence",
        "criterion_model_name": criteria_config.get("name"),
        "criterion_weights": {item["key"]: item.get("weight") for item in criteria},
        "minimum_evidence_coverage_percent": criteria_config.get("minimum_evidence_coverage_percent", 60),
        "records_exported": len(output_records),
        "criteria_per_record": 6,
        "candidate_evidence_counts": {
            item["key"]: sum(c["candidate_evidence_count"] for record in output_records for c in record["criteria"] if c["key"] == item["key"])
            for item in criteria
        },
        "records_with_any_candidate_evidence": sum(any(c["candidate_evidence_count"] for c in record["criteria"]) for record in output_records),
        "records_with_scores": sum(record.get("qualification_score") is not None for record in output_records),
        "canonical_criterion_reviews_changed": False,
        "qualification_scores_changed": False,
        "outreach_enabled": False,
        "note": "Candidate evidence is mapped to the existing six criteria; assessment statuses and scores reflect the validated qualification export. Candidate evidence alone never confirms or rules out a criterion.",
        "records": output_records,
    }


def write_criterion_evidence(prospect_path: Path, criteria_path: Path, public_path: Path, security_path: Path, trigger_path: Path, output_path: Path) -> dict[str, Any]:
    prospect = json.loads(prospect_path.read_text(encoding="utf-8"))
    criteria = json.loads(criteria_path.read_text(encoding="utf-8"))
    public = json.loads(public_path.read_text(encoding="utf-8")) if public_path.is_file() else None
    security = json.loads(security_path.read_text(encoding="utf-8")) if security_path.is_file() else None
    trigger = json.loads(trigger_path.read_text(encoding="utf-8")) if trigger_path.is_file() else None
    result = build_criterion_evidence(prospect, criteria, public, security, trigger)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_exported", "criteria_per_record", "candidate_evidence_counts", "records_with_any_candidate_evidence", "records_with_scores", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--criteria", type=Path, default=Path("config/qualification_criteria.json"))
    parser.add_argument("--public-research", type=Path, default=Path("artifacts/automated-research.json"))
    parser.add_argument("--security-research", type=Path, default=Path("artifacts/security-research.json"))
    parser.add_argument("--trigger-research", type=Path, default=Path("artifacts/trigger-research.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/criterion-evidence.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(write_criterion_evidence(args.input, args.criteria, args.public_research, args.security_research, args.trigger_research, args.output), indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
