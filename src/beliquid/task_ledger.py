"""Build task-ledger completions from source calls that actually ran successfully.

A task completion records that an automated research pass executed, not that the
prospect passed identity, security, buying-trigger, or qualification checks.
Failed or unsupported source calls never produce completion records.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from beliquid.research_queue import record_fingerprint


def _key(record: dict[str, Any]) -> str:
    return f"{str(record.get('chain') or '').strip().casefold()}:{str(record.get('contract_address') or '').strip().casefold()}"


def _source_record_map(payload: Any, label: str) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{label} must contain a records list")
    result = {}
    for record in payload["records"]:
        if not isinstance(record, dict):
            raise ValueError(f"{label} records must be objects")
        key = _key(record)
        if key.startswith(":") or key.endswith(":"):
            raise ValueError(f"{label} record is missing chain or contract address")
        if key in result:
            raise ValueError(f"duplicate {label} record: {key}")
        result[key] = record
    return result


def _completion(task: str, record: dict[str, Any], evidence: list[tuple[str, str]], outcome: str, now: str) -> dict[str, Any] | None:
    pairs = [(url, timestamp) for url, timestamp in evidence if isinstance(url, str) and url.startswith(("https://", "http://")) and isinstance(timestamp, str) and timestamp.strip()]
    if not pairs:
        return None
    return {
        "status": "completed",
        "reviewer": "automated-research-pipeline",
        "completed_at": now,
        "outcome": outcome,
        "evidence_urls": [url for url, _ in pairs],
        "evidence_timestamps": [stamp for _, stamp in pairs],
        "input_fingerprint": record_fingerprint(record),
    }


def build_task_ledger(
    prospect_payload: dict[str, Any],
    public_research: dict[str, Any] | None,
    security_research: dict[str, Any] | None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    records = prospect_payload.get("records")
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("prospect-review input must contain a records list of objects")
    public_by_key = _source_record_map(public_research, "automated public research")
    security_by_key = _source_record_map(security_research, "automated security research")
    now = completed_at or datetime.now(timezone.utc).isoformat()
    ledger: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _key(record)
        if key.startswith(":") or key.endswith(":"):
            raise ValueError("prospect record is missing chain or contract address")
        tasks: dict[str, Any] = {}

        # Record identity/risk research as inconclusive only if at least one real
        # source response succeeded (including an explicit no-report response).
        identity_evidence: list[tuple[str, str]] = []
        public = public_by_key.get(key, {})
        page = public.get("page") or {}
        if public.get("fetch_status") == "success" and page.get("final_url"):
            identity_evidence.append((page["final_url"], public.get("observed_at", now)))
        security = security_by_key.get(key, {})
        if security.get("fetch_status") in {"success", "no_report"} and security.get("provider_url"):
            identity_evidence.append((security["provider_url"], security.get("observed_at", now)))
        entry = _completion("verify_identity_and_risk", record, identity_evidence, "inconclusive", now)
        if entry:
            tasks["verify_identity_and_risk"] = entry

        # Market research is complete only where the run recorded an actual
        # DEX Screener enrichment observation; missing metrics remain inconclusive.
        market_evidence = [
            (item.get("source_url"), item.get("observed_at"))
            for item in record.get("evidence", [])
            if isinstance(item, dict) and item.get("evidence_type") == "token_market_enrichment"
        ]
        metrics = record.get("metrics") or {}
        metric_values = [metrics.get(name) for name in ("liquidity_usd", "volume_24h_usd", "market_cap_usd", "fdv_usd")]
        outcome = "completed" if any(isinstance(value, (int, float)) for value in metric_values) else "inconclusive"
        entry = _completion("investigate_market_quality", record, market_evidence, outcome, now)
        if entry:
            tasks["investigate_market_quality"] = entry

        # Keyword trigger search is considered an executed, inconclusive pass only
        # when the public page was actually fetched. Candidates remain unverified.
        if public.get("fetch_status") == "success" and page.get("final_url"):
            entry = _completion(
                "research_buying_triggers", record,
                [(page["final_url"], public.get("observed_at", now))],
                "inconclusive", now,
            )
            if entry:
                tasks["research_buying_triggers"] = entry

        if tasks:
            ledger[key] = tasks

    return {
        "schema_version": 1,
        "generated_at": now,
        "executor": "automated-research-pipeline",
        "records_with_task_completions": len(ledger),
        "task_completion_counts": {
            task: sum(task in entries for entries in ledger.values())
            for task in ("verify_identity_and_risk", "investigate_market_quality", "research_buying_triggers", "complete_criterion_evidence")
        },
        "policy": {
            "completion_means_research_executed_not_cleared": True,
            "failed_or_unsupported_sources_marked_completed": False,
            "identity_and_risk_clearance_changed": False,
            "qualification_scores_changed": False,
            "outreach_enabled": False,
        },
        "reviews": ledger,
    }


def write_task_ledger(prospect_path: Path, public_path: Path, security_path: Path, output_path: Path) -> dict[str, Any]:
    prospect = json.loads(prospect_path.read_text(encoding="utf-8"))
    public = json.loads(public_path.read_text(encoding="utf-8")) if public_path.is_file() else None
    security = json.loads(security_path.read_text(encoding="utf-8")) if security_path.is_file() else None
    if not isinstance(prospect, dict):
        raise ValueError("prospect-review input must be a JSON object")
    result = build_task_ledger(prospect, public, security)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_with_task_completions", "task_completion_counts", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--public-research", type=Path, default=Path("artifacts/automated-research.json"))
    parser.add_argument("--security-research", type=Path, default=Path("artifacts/security-research.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/research-task-ledger.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(write_task_ledger(args.input, args.public_research, args.security_research, args.output), indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
