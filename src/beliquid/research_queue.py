"""Generate an automation-first research queue with auditable task completion records."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

TASK_ORDER = {
    "resolve_manual_hold": 0,
    "verify_identity_and_risk": 1,
    "investigate_market_quality": 2,
    "research_buying_triggers": 3,
    "complete_criterion_evidence": 4,
    "follow_up_incomplete_research": 5,
}
COMPLETABLE_TASKS = {
    "verify_identity_and_risk", "investigate_market_quality",
    "research_buying_triggers", "complete_criterion_evidence",
}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "insufficient_data": 3}


def _key(record: dict[str, Any]) -> str:
    chain, contract = record.get("chain"), record.get("contract_address")
    if not isinstance(chain, str) or not chain.strip():
        raise ValueError("each prospect requires a non-empty chain")
    if not isinstance(contract, str) or not contract.strip():
        raise ValueError("each prospect requires a non-empty contract_address for ledger matching")
    return f"{chain.strip().casefold()}:{contract.strip().casefold()}"


def record_fingerprint(record: dict[str, Any]) -> str:
    """Fingerprint the exact current record; changed metrics/evidence reopen work."""
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_task_reviews(payload: Any, records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("task review ledger must be an object with schema_version 1")
    reviews = payload.get("reviews")
    if not isinstance(reviews, dict):
        raise ValueError("task review ledger reviews must be an object")
    current_keys = {_key(record) for record in records}
    unknown_keys = sorted(set(reviews) - current_keys)
    if unknown_keys:
        raise ValueError("task review key(s) do not match this batch: " + ", ".join(unknown_keys))
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    allowed_outcomes = {"completed", "inconclusive", "blocked", "needs_follow_up"}
    for prospect_key, tasks in reviews.items():
        if not isinstance(prospect_key, str) or not isinstance(tasks, dict):
            raise ValueError("each task review entry must map a prospect key to a task object")
        normalized_key = prospect_key.strip().casefold()
        if normalized_key not in current_keys:
            raise ValueError(f"invalid prospect key in task ledger: {prospect_key}")
        normalized[normalized_key] = {}
        for task, entry in tasks.items():
            if task not in COMPLETABLE_TASKS or not isinstance(entry, dict):
                raise ValueError(f"unsupported task review entry: {task}")
            if entry.get("status") != "completed":
                raise ValueError(f"task review {task} status must be completed")
            for field in ("reviewer", "completed_at", "outcome", "input_fingerprint"):
                if not isinstance(entry.get(field), str) or not entry[field].strip():
                    raise ValueError(f"task review {task} requires non-empty {field}")
            try:
                stamp = datetime.fromisoformat(entry["completed_at"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"task review {task} completed_at must be timezone-aware ISO 8601") from exc
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError(f"task review {task} completed_at must be timezone-aware ISO 8601")
            if entry["outcome"] not in allowed_outcomes:
                raise ValueError(f"task review {task} has unsupported outcome")
            urls, times = entry.get("evidence_urls"), entry.get("evidence_timestamps")
            if not isinstance(urls, list) or not urls or not all(
                isinstance(url, str) and url.startswith(("https://", "http://")) for url in urls
            ):
                raise ValueError(f"task review {task} requires HTTP(S) evidence_urls")
            if not isinstance(times, list) or len(times) != len(urls):
                raise ValueError(f"task review {task} evidence URLs/timestamps must be paired")
            for timestamp in times:
                if not isinstance(timestamp, str) or not timestamp.strip():
                    raise ValueError(f"task review {task} evidence timestamps must be non-empty strings")
                try:
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError(f"task review {task} evidence timestamp must be ISO 8601") from exc
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError(f"task review {task} evidence timestamps must be timezone-aware")
            normalized[normalized_key][task] = entry
    return normalized


def _is_current_completion(entry: dict[str, Any] | None, record: dict[str, Any]) -> bool:
    return bool(entry and entry.get("input_fingerprint") == record_fingerprint(record))


def _next_task(record: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> tuple[str, str]:
    identity = record.get("identity_risk") or {}
    identity_status = identity.get("identity_status", "unknown")
    risk_status = identity.get("risk_status", "unknown")
    route = identity.get("action_route", record.get("action_route", "research"))

    # A documented hold is a terminal automated disposition, not a human task.
    if route == "manual_hold" or identity_status == "mismatch" or risk_status == "concern":
        return "resolve_manual_hold", "Automated hold: documented identity mismatch or risk concern; excluded from the cleared list."

    # Identity/risk checks run first. If unresolved after a current research pass,
    # continue commercial research but preserve the unresolved clearance status.
    if identity_status != "verified" or risk_status != "clear":
        if not _is_current_completion(reviews.get("verify_identity_and_risk"), record):
            return "verify_identity_and_risk", "Automated identity/risk research; unresolved results do not imply clearance."
        # Research can continue. Qualification/disposition remains not-cleared below.

    market = record.get("market_research_priority") or {}
    if market.get("priority") == "high" and not _is_current_completion(reviews.get("investigate_market_quality"), record):
        return "investigate_market_quality", "Validate selected-pool market data; activity is not buying intent or permission to contact."
    triggers = record.get("buying_triggers") or {}
    if not triggers.get("verified_count", 0) and not _is_current_completion(reviews.get("research_buying_triggers"), record):
        return "research_buying_triggers", "Research dated, source-backed buying triggers; market metrics alone do not establish intent."
    qualification = record.get("qualification") or {}
    if qualification.get("score_percent") is None:
        if not _is_current_completion(reviews.get("complete_criterion_evidence"), record):
            return "complete_criterion_evidence", "Collect criterion-specific evidence; preserve unknowns and withhold unsupported scores."
        return "follow_up_incomplete_research", "Automated evidence pass completed but score remains withheld; record an explicit insufficient-evidence disposition."
    return "follow_up_incomplete_research", "Research queue complete for this snapshot; automated disposition follows evidence coverage and identity/risk clearance rules."


def build_research_queue(payload: dict[str, Any], task_reviews: Any = None) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("prospect-review input must contain a records list")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("each prospect record must be an object")
    reviews = validate_task_reviews(task_reviews or {"schema_version": 1, "reviews": {}}, records)
    tasks, seen = [], set()
    for record in records:
        name, chain, contract = record.get("project_name"), record.get("chain"), record.get("contract_address")
        if not isinstance(name, str) or not isinstance(chain, str):
            raise ValueError("each prospect requires project_name and chain")
        key = _key(record)
        if key in seen:
            raise ValueError(f"duplicate prospect in queue input: {chain}:{contract}")
        seen.add(key)
        task, rationale = _next_task(record, reviews.get(key, {}))
        market, identity = record.get("market_research_priority") or {}, record.get("identity_risk") or {}
        qualification = record.get("qualification") or {}
        signals = market.get("signals", [])
        if not isinstance(signals, list) or not all(isinstance(x, str) for x in signals):
            raise ValueError(f"market priority signals must be a list of strings for {key}")
        current = reviews.get(key, {}).get(task)
        identity_status = identity.get("identity_status", "unknown")
        risk_status = identity.get("risk_status", "unknown")
        is_cleared = identity_status == "verified" and risk_status == "clear" and task != "resolve_manual_hold"
        tasks.append({
            "task_order": TASK_ORDER[task], "task": task, "project_name": name, "chain": chain,
            "contract_address": contract, "website_url_candidate": record.get("website_url_candidate"),
            "identity_status": identity_status, "risk_status": risk_status,
            "clearance_status": "cleared" if is_cleared else ("held" if task == "resolve_manual_hold" else "unresolved"),
            "action_route": identity.get("action_route", record.get("action_route", "research")),
            "market_priority": market.get("priority", "insufficient_data"),
            "market_priority_signals": ";".join(signals),
            "buying_trigger_status": (record.get("buying_triggers") or {}).get("status", "unknown"),
            "evidence_coverage_percent": qualification.get("evidence_coverage_percent", 0),
            "score_status": qualification.get("score_status", "insufficient_evidence"),
            "completion_record_status": "completed_current_snapshot" if _is_current_completion(current, record) else "open",
            "input_fingerprint": record_fingerprint(record),
            "outreach_enabled": False, "blocked_by_hold": task == "resolve_manual_hold",
            "rationale": rationale,
        })
    tasks.sort(key=lambda x: (x["task_order"], PRIORITY_ORDER.get(x["market_priority"], 4), x["project_name"].casefold(), x["chain"].casefold(), str(x["contract_address"] or "").casefold()))
    return {
        "schema_version": 3, "source": "prospect-review.json", "records_exported": len(tasks),
        "task_counts": {task: sum(x["task"] == task for x in tasks) for task in TASK_ORDER},
        "policy": {"manual_holds_first": True, "identity_and_risk_precede_commercial_research": True,
                   "unresolved_identity_risk_blocks_clearance_not_research": True,
                   "market_metrics_prove_buying_intent": False, "unknowns_preserved": True,
                   "completion_is_not_clearance": True, "stale_fingerprints_reopen_tasks": True,
                   "human_review_required": False, "outreach_enabled": False, "priority_thresholds_validated": False},
        "tasks": tasks,
    }


def write_research_queue(input_path: Path, output_dir: Path, reviews_path: Path | None = None) -> dict[str, str]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        review_payload = json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path else {"schema_version": 1, "reviews": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read queue input/review JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("prospect-review input must be a JSON object")
    queue = build_research_queue(payload, review_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    jp, cp = output_dir / "research-queue.json", output_dir / "research-queue.csv"
    jp.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = list(queue["tasks"][0]) if queue["tasks"] else ["task_order", "task", "project_name", "chain", "contract_address", "outreach_enabled", "blocked_by_hold", "rationale"]
    with cp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(queue["tasks"])
    return {"json": str(jp), "csv": str(cp), "records_exported": str(len(queue["tasks"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--reviews", type=Path, default=Path("config/research_task_reviews.json"))
    args = parser.parse_args()
    print(json.dumps(write_research_queue(args.input, args.output_dir, args.reviews), indent=2))


if __name__ == "__main__":
    main()
