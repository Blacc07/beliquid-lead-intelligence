"""Rebuild the final review exports after automated evidence assessment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from beliquid.models import Evidence, ProspectRecord
from beliquid.review_export import write_review_exports


def rebuild_exports(input_path: Path, summary_path: Path, output_dir: Path, criterion_reviews_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("input prospect export must contain a records list")
    records = []
    for row in payload["records"]:
        if not isinstance(row, dict):
            raise ValueError("prospect rows must be objects")
        evidence = []
        for item in row.get("evidence", []):
            if not isinstance(item, dict):
                continue
            if not item.get("source_name") or not item.get("source_url") or not item.get("observed_at"):
                continue
            evidence.append(Evidence(
                source_name=str(item["source_name"]), source_url=str(item["source_url"]),
                observed_at=str(item["observed_at"]), evidence_type=str(item.get("evidence_type") or "discovery"),
                notes=item.get("notes"),
            ))
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        records.append(ProspectRecord(
            project_name=str(row.get("project_name") or ""),
            chain=str(row.get("chain") or ""),
            contract_address=row.get("contract_address"),
            website_url=row.get("website_url_candidate"),
            token_symbol=row.get("token_symbol"),
            metrics=metrics,
            evidence=tuple(evidence),
        ))
    result = write_review_exports(
        records, summary, output_dir,
        criterion_reviews_path=criterion_reviews_path,
    )
    return {"status": "written", "records_exported": len(records), **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--summary", type=Path, default=Path("artifacts/pipeline-summary.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--criterion-reviews", type=Path, default=Path("artifacts/automated-criterion-reviews.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(rebuild_exports(args.input, args.summary, args.output_dir, args.criterion_reviews), indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
