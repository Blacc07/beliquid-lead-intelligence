"""Generate a conservative human research queue from prospect-review.json."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from typing import Any

TASK_ORDER = {"resolve_manual_hold": 0, "verify_identity_and_risk": 1, "investigate_market_quality": 2, "research_buying_triggers": 3, "complete_criterion_evidence": 4, "independent_human_review": 5}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "insufficient_data": 3}

def _next_task(record: dict[str, Any]) -> tuple[str, str]:
    identity = record.get("identity_risk") or {}
    identity_status = identity.get("identity_status", "unknown")
    risk_status = identity.get("risk_status", "unknown")
    route = identity.get("action_route", record.get("action_route", "research"))
    if route == "manual_hold" or identity_status == "mismatch" or risk_status == "concern":
        return "resolve_manual_hold", "Resolve the documented identity mismatch or risk concern; all downstream work is blocked."
    if identity_status != "verified" or risk_status != "clear":
        return "verify_identity_and_risk", "Verify chain, contract, official domain, and independent security/reputation sources; preserve unknowns until evidenced."
    market = record.get("market_research_priority") or {}
    if market.get("priority") == "high":
        return "investigate_market_quality", "Validate selected-pool market data and investigate the signal; it is not buying intent or permission to contact."
    triggers = record.get("buying_triggers") or {}
    if not triggers.get("verified_count", 0):
        return "research_buying_triggers", "Research dated, source-backed buying triggers; market metrics alone do not establish intent."
    qualification = record.get("qualification") or {}
    if qualification.get("score_percent") is None:
        return "complete_criterion_evidence", "Complete criterion-specific evidence review; unknown is not a negative finding."
    return "independent_human_review", "Request independent human review of evidence and qualification; outreach remains disabled."

def build_research_queue(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("prospect-review input must contain a records list")
    tasks, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each prospect record must be an object")
        name, chain, contract = record.get("project_name"), record.get("chain"), record.get("contract_address")
        if not isinstance(name, str) or not isinstance(chain, str):
            raise ValueError("each prospect requires project_name and chain")
        key = (chain.casefold(), str(contract or name).casefold())
        if key in seen:
            raise ValueError(f"duplicate prospect in queue input: {chain}:{contract or name}")
        seen.add(key)
        task, rationale = _next_task(record)
        market = record.get("market_research_priority") or {}
        identity = record.get("identity_risk") or {}
        qualification = record.get("qualification") or {}
        tasks.append({
            "task_order": TASK_ORDER[task], "task": task, "project_name": name, "chain": chain,
            "contract_address": contract, "website_url_candidate": record.get("website_url_candidate"),
            "identity_status": identity.get("identity_status", "unknown"), "risk_status": identity.get("risk_status", "unknown"),
            "action_route": identity.get("action_route", record.get("action_route", "research")),
            "market_priority": market.get("priority", "insufficient_data"),
            "market_priority_signals": ";".join(market.get("signals", [])),
            "buying_trigger_status": (record.get("buying_triggers") or {}).get("status", "unknown"),
            "evidence_coverage_percent": qualification.get("evidence_coverage_percent", 0),
            "score_status": qualification.get("score_status", "insufficient_evidence"),
            "outreach_enabled": False, "blocked_by_hold": task == "resolve_manual_hold", "rationale": rationale,
        })
    tasks.sort(key=lambda x: (x["task_order"], PRIORITY_ORDER.get(x["market_priority"], 4), x["project_name"].casefold(), x["chain"].casefold(), str(x["contract_address"] or "").casefold()))
    return {"schema_version": 1, "source": "prospect-review.json", "records_exported": len(tasks),
            "task_counts": {task: sum(x["task"] == task for x in tasks) for task in TASK_ORDER},
            "policy": {"manual_holds_first": True, "identity_and_risk_precede_commercial_research": True,
                       "market_metrics_prove_buying_intent": False, "unknowns_preserved": True,
                       "outreach_enabled": False, "priority_thresholds_validated": False}, "tasks": tasks}

def write_research_queue(input_path: Path, output_dir: Path) -> dict[str, str]:
    try: payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"Could not read prospect review JSON: {exc}") from exc
    if not isinstance(payload, dict): raise ValueError("prospect-review input must be a JSON object")
    queue = build_research_queue(payload); output_dir.mkdir(parents=True, exist_ok=True)
    jp, cp = output_dir / "research-queue.json", output_dir / "research-queue.csv"
    jp.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = list(queue["tasks"][0]) if queue["tasks"] else ["task_order", "task", "project_name", "chain", "contract_address", "outreach_enabled", "blocked_by_hold", "rationale"]
    with cp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(queue["tasks"])
    return {"json": str(jp), "csv": str(cp), "records_exported": str(len(queue["tasks"]))}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    print(json.dumps(write_research_queue(args.input, args.output_dir), indent=2))
if __name__ == "__main__": main()
