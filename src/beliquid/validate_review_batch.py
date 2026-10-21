"""Validate review inputs, export parity, and write an artifact provenance manifest.

This is a fail-closed batch gate. It validates data integrity, not whether cited
sources are truthful or whether a human reviewer made a sound judgment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from beliquid.buying_triggers import load_buying_trigger_reviews
from beliquid.criterion_reviews import load_criterion_reviews
from beliquid.identity_risk import load_identity_risk_reviews
from beliquid.qualification import load_criteria_config

REVIEW_FILES = {
    "criterion_reviews": Path("config/criterion_reviews.json"),
    "identity_risk_reviews": Path("config/identity_risk_reviews.json"),
    "buying_trigger_reviews": Path("config/buying_trigger_reviews.json"),
    "qualification_criteria": Path("config/qualification_criteria.json"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _key(chain: Any, contract: Any) -> str:
    if not isinstance(chain, str) or not chain.strip():
        raise ValueError("prospect record has missing chain")
    if not isinstance(contract, str) or not contract.strip():
        raise ValueError("prospect record has missing contract_address")
    return f"{chain.strip().casefold()}:{contract.strip().casefold()}"


def _float_equal(csv_value: str, json_value: Any, label: str, key: str) -> None:
    if json_value is None:
        if csv_value not in ("", "None", "null"):
            raise ValueError(f"CSV/JSON mismatch for {key} {label}: expected blank, got {csv_value!r}")
        return
    try:
        left = float(csv_value)
        right = float(json_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CSV/JSON non-numeric {label} for {key}") from exc
    if abs(left - right) > 1e-6:
        raise ValueError(f"CSV/JSON mismatch for {key} {label}: {left} != {right}")


def validate_batch(artifacts_dir: Path, repo_root: Path = Path(".")) -> dict[str, Any]:
    """Validate three reviewer inputs, prospect-key integrity, and CSV/JSON parity."""
    csv_path = artifacts_dir / "prospect-review.csv"
    json_path = artifacts_dir / "prospect-review.json"
    summary_path = artifacts_dir / "pipeline-summary.json"
    for path in (csv_path, json_path, summary_path):
        if not path.is_file():
            raise ValueError(f"required batch artifact missing: {path}")

    config = load_criteria_config(repo_root / REVIEW_FILES["qualification_criteria"])
    criterion_reviews = load_criterion_reviews(repo_root / REVIEW_FILES["criterion_reviews"], config)
    identity_reviews = load_identity_risk_reviews(repo_root / REVIEW_FILES["identity_risk_reviews"])
    trigger_reviews = load_buying_trigger_reviews(repo_root / REVIEW_FILES["buying_trigger_reviews"])

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 7:
        raise ValueError(f"unsupported prospect-review schema version: {payload.get('schema_version')!r}")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("records_exported") != len(records):
        raise ValueError("JSON records and records_exported count disagree")

    record_by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _key(record.get("chain"), record.get("contract_address"))
        if key in record_by_key:
            raise ValueError(f"duplicate prospect identity in JSON export: {key}")
        record_by_key[key] = record

    for label, reviews in (
        ("criterion", criterion_reviews),
        ("identity/risk", identity_reviews),
        ("buying-trigger", trigger_reviews),
    ):
        unknown_keys = sorted(set(reviews) - set(record_by_key))
        if unknown_keys:
            raise ValueError(
                f"{label} review key(s) do not match any prospect in this batch: "
                + ", ".join(unknown_keys)
            )

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    if len(csv_rows) != len(records):
        raise ValueError(f"CSV/JSON record count mismatch: {len(csv_rows)} != {len(records)}")

    criteria_keys = [item["key"] for item in config["criteria"]]
    comparisons = 0
    for csv_row in csv_rows:
        key = _key(csv_row.get("chain"), csv_row.get("contract_address"))
        record = record_by_key.get(key)
        if record is None:
            raise ValueError(f"CSV prospect identity missing from JSON export: {key}")
        qualification = record.get("qualification", {})
        identity = record.get("identity_risk", {})
        triggers = record.get("buying_triggers", {})
        checks = {
            "project_name": record.get("project_name"),
            "token_symbol": record.get("token_symbol"),
            "action_route": record.get("action_route"),
            "identity_status": identity.get("identity_status"),
            "identity_evidence_url": identity.get("identity_evidence_url") or "",
            "identity_observed_at": identity.get("identity_observed_at") or "",
            "risk_status": identity.get("risk_status"),
            "risk_evidence_url": identity.get("risk_evidence_url") or "",
            "risk_observed_at": identity.get("risk_observed_at") or "",
            "identity_risk_reviewer_note": identity.get("reviewer_note") or "",
            "identity_risk_flags": ";".join(identity.get("review_flags", [])),
            "buying_trigger_status": triggers.get("status"),
            "buying_trigger_count": str(triggers.get("trigger_count", 0)),
            "verified_trigger_count": str(triggers.get("verified_count", 0)),
            "inferred_trigger_count": str(triggers.get("inferred_count", 0)),
            "buying_triggers_json": json.dumps(triggers.get("triggers", []), sort_keys=True),
            "score_status": qualification.get("score_status"),
            "review_flags": ";".join(qualification.get("review_flags", [])),
            "outreach_enabled": str(bool(qualification.get("outreach_enabled"))).lower(),
        }
        for field, expected in checks.items():
            if csv_row.get(field, "") != str(expected):
                raise ValueError(
                    f"CSV/JSON mismatch for {key} field {field}: "
                    f"{csv_row.get(field, '')!r} != {expected!r}"
                )
            comparisons += 1
        _float_equal(csv_row.get("score_percent", ""), qualification.get("score_percent"), "score_percent", key)
        _float_equal(csv_row.get("evidence_coverage_percent", ""), qualification.get("evidence_coverage_percent"), "evidence_coverage_percent", key)
        comparisons += 2

        criterion_reports = {
            item.get("criterion"): item
            for item in qualification.get("criteria", [])
            if isinstance(item, dict)
        }
        if set(criterion_reports) != set(criteria_keys):
            raise ValueError(f"JSON qualification criteria do not match configured six criteria for {key}")
        for criterion in criteria_keys:
            item = criterion_reports[criterion]
            status = item.get("status", "unknown")
            if csv_row.get(f"{criterion}_status") != status:
                raise ValueError(f"CSV/JSON mismatch for {key} {criterion}_status")
            comparisons += 1
            if csv_row.get(f"review_{criterion}_status") != status:
                raise ValueError(f"CSV/JSON mismatch for {key} review status {criterion}")
            comparisons += 1
            for field, json_field in (
                ("evidence_urls_json", "evidence_urls"),
                ("evidence_timestamps_json", "evidence_timestamps"),
            ):
                column = f"review_{criterion}_{field}"
                try:
                    actual = json.loads(csv_row.get(column, ""))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON in CSV field {column} for {key}") from exc
                expected = item.get(json_field, [])
                if actual != expected:
                    raise ValueError(f"CSV/JSON mismatch for {key} {criterion} {json_field}")
                comparisons += 1
            if csv_row.get(f"review_{criterion}_reviewer_note", "") != (item.get("note") or ""):
                raise ValueError(f"CSV/JSON mismatch for {key} {criterion} reviewer note")
            if csv_row.get(f"review_{criterion}_review_flag", "") != (item.get("review_flag") or ""):
                raise ValueError(f"CSV/JSON mismatch for {key} {criterion} review flag")
            comparisons += 2
            urls = item.get("evidence_urls", [])
            timestamps = item.get("evidence_timestamps", [])
            if len(urls) != len(timestamps):
                raise ValueError(f"evidence URL/timestamp count mismatch for {key} {criterion}")

        if qualification.get("outreach_enabled") is not False:
            raise ValueError(f"outreach safeguard violated for {key}")
        if identity.get("identity_status") == "mismatch" or identity.get("risk_status") == "concern":
            if record.get("action_route") != "manual_hold":
                raise ValueError(f"identity/risk hold did not override route for {key}")
        elif identity.get("identity_status") == "verified" and identity.get("risk_status") == "clear":
            if record.get("action_route") != "business_development_review":
                raise ValueError(f"verified+clear route incorrect for {key}")
        elif record.get("action_route") != "research":
            raise ValueError(f"unresolved identity/risk must remain research for {key}")

        if qualification.get("evidence_coverage_percent", 0) < config["minimum_evidence_coverage_percent"]:
            if qualification.get("score_percent") is not None or qualification.get("score_status") != "insufficient_evidence":
                raise ValueError(f"score must be withheld below coverage threshold for {key}")
        if any(item.get("status") == "unknown" for item in criterion_reports.values()):
            # Unknown does not itself prevent a score if the remaining assessed weight
            # still meets the configured threshold, so only ensure unknown is not counted.
            unknown_weight = sum(item["weight"] for item in criterion_reports.values() if item.get("status") == "unknown")
            assessed_weight = qualification.get("assessed_weight")
            if assessed_weight != sum(item["weight"] for item in criterion_reports.values() if item.get("status") != "unknown"):
                raise ValueError(f"unknown criterion weight counted as assessed for {key}")

    if payload.get("qualification_summary", {}).get("outreach_enabled") is not False:
        raise ValueError("qualification summary must keep outreach disabled")
    if summary.get("qualification", {}).get("outreach_enabled") is not False:
        raise ValueError("pipeline summary must keep outreach disabled")

    return {
        "validation_status": "passed",
        "records_validated": len(records),
        "csv_json_field_comparisons": comparisons,
        "criterion_review_records_loaded": len(criterion_reviews),
        "identity_risk_review_records_loaded": len(identity_reviews),
        "buying_trigger_review_records_loaded": len(trigger_reviews),
        "scores_issued": sum(item["qualification"].get("score_percent") is not None for item in records),
        "scores_withheld": sum(item["qualification"].get("score_percent") is None for item in records),
        "manual_holds": sum(item.get("action_route") == "manual_hold" for item in records),
        "outreach_enabled": False,
    }


def write_audit_manifest(artifacts_dir: Path, validation: dict[str, Any], repo_root: Path = Path(".")) -> Path:
    """Write run provenance and SHA-256 hashes for review inputs and generated exports."""
    input_hashes = {}
    for name, relative in REVIEW_FILES.items():
        path = repo_root / relative
        if not path.is_file():
            raise ValueError(f"review input/config missing for audit manifest: {path}")
        input_hashes[str(relative)] = _sha256(path)
    output_hashes = {}
    for name in ("prospect-review.csv", "prospect-review.json", "pipeline-summary.json"):
        path = artifacts_dir / name
        output_hashes[name] = _sha256(path)
    manifest = {
        "manifest_schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workflow": {
            "name": os.environ.get("GITHUB_WORKFLOW"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_number": os.environ.get("GITHUB_RUN_NUMBER"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "ref": os.environ.get("GITHUB_REF"),
            "commit_sha": os.environ.get("GITHUB_SHA"),
            "event_name": os.environ.get("GITHUB_EVENT_NAME"),
        },
        "validation": validation,
        "review_input_sha256": input_hashes,
        "export_sha256": output_hashes,
        "note": "Hashes provide integrity/provenance checks, not proof that cited evidence is truthful. Outreach is disabled.",
    }
    path = artifacts_dir / "audit-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_batch(args.artifacts_dir, args.repo_root)
        if args.write_manifest:
            manifest_path = write_audit_manifest(args.artifacts_dir, result, args.repo_root)
            result["audit_manifest"] = str(manifest_path)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"validation_status": "failed", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
