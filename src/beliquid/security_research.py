"""Automated contract-risk observations from GoPlus Security API.

The adapter emits source-scoped observations only. A clean or missing GoPlus report is
not a global risk clearance, and this module never changes canonical identity/risk
reviews, qualification scores, dispositions, or outreach settings.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
API_ROOT = "https://api.gopluslabs.io/api/v1/token_security"
USER_AGENT = "BeLiquid-Lead-Intelligence/0.1 (+https://github.com/Blacc07/beliquid-lead-intelligence)"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 1_000_000
MAX_ATTEMPTS = 3

# GoPlus uses chain IDs in this endpoint. Unknown chain names deliberately stay unsupported.
CHAIN_IDS = {
    "ethereum": "1", "eth": "1",
    "bsc": "56", "bnb chain": "56", "binance smart chain": "56",
    "polygon": "137", "polygon pos": "137",
    "arbitrum": "42161", "arbitrum one": "42161",
    "optimism": "10", "base": "8453",
    "avalanche": "43114", "avalanche c-chain": "43114",
    "fantom": "250", "cronos": "25", "gnosis": "100",
    "linea": "59144", "scroll": "534352", "mantle": "5000",
}

# These flags are strong contract-level concerns when explicitly reported as true.
CRITICAL_FLAGS = {
    "is_honeypot": "provider reports honeypot behavior",
    "cannot_sell_all": "provider reports that some holders may be unable to sell",
    "hidden_owner": "provider reports a hidden owner capability",
    "selfdestruct": "provider reports a self-destruct capability",
    "external_call": "provider reports an external-call capability",
    "owner_change_balance": "provider reports owner-controlled balance changes",
}


def _truthy_flag(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes"}


def _default_request(url: str, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("GoPlus response exceeded 1 MB limit")
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("GoPlus response must be a JSON object")
    return parsed


def fetch_token_security(chain_id: str, address: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    """Fetch one token security record, retrying only transient network/API failures."""
    url = f"{API_ROOT}/{chain_id}?{urlencode({'contract_addresses': address})}"
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return requester(url)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == MAX_ATTEMPTS - 1:
                raise
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS - 1:
                raise
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(0.25 * (2 ** attempt))
    if last_error:
        raise last_error
    raise RuntimeError("GoPlus request ended without a response")


def research_security(record: dict[str, Any], observed_at: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    chain = str(record.get("chain") or "").strip().casefold()
    address = str(record.get("contract_address") or "").strip()
    result: dict[str, Any] = {
        "project_name": record.get("project_name", ""),
        "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""),
        "provider": "GoPlus Token Security API",
        "provider_url": None,
        "observed_at": observed_at,
        "fetch_status": "not_attempted",
        "provider_report_status": "unknown",
        "risk_status": "unknown",
        "findings": [],
        "outreach_enabled": False,
    }
    chain_id = CHAIN_IDS.get(chain)
    if not chain_id:
        result.update(fetch_status="unsupported_chain", research_note="No configured GoPlus chain mapping; risk remains unknown.")
        return result
    if not address:
        result.update(fetch_status="missing_contract_address", research_note="No contract address supplied; risk remains unknown.")
        return result

    url = f"{API_ROOT}/{chain_id}?{urlencode({'contract_addresses': address})}"
    result["provider_url"] = url
    try:
        payload = fetch_token_security(chain_id, address, requester)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result.update(fetch_status="fetch_failed", research_note=f"GoPlus request failed ({type(exc).__name__}); risk remains unknown.")
        return result

    if payload.get("code") not in (None, 1, "1", 200, "200"):
        result.update(fetch_status="provider_error", research_note="GoPlus returned an API error; risk remains unknown.")
        return result
    data = payload.get("result")
    if not isinstance(data, dict):
        result.update(fetch_status="no_report", provider_report_status="not_found", research_note="GoPlus returned no token report; this is not evidence of safety.")
        return result
    report = data.get(address) or data.get(address.lower()) or data.get(address.upper())
    if not isinstance(report, dict) or not report:
        result.update(fetch_status="no_report", provider_report_status="not_found", research_note="GoPlus returned no matching contract report; this is not evidence of safety.")
        return result

    findings = []
    for field, description in CRITICAL_FLAGS.items():
        if field in report and _truthy_flag(report[field]):
            findings.append({"field": field, "value": str(report[field]), "severity": "high", "description": description})
    for field in ("is_mintable", "is_proxy", "is_blacklisted", "transfer_pausable", "trading_cooldown", "cannot_buy"):
        if field in report and _truthy_flag(report[field]):
            findings.append({"field": field, "value": str(report[field]), "severity": "review", "description": "Provider-reported contract capability requiring context"})
    result.update({
        "fetch_status": "success",
        "provider_report_status": "found",
        "risk_status": "concern" if any(item["severity"] == "high" for item in findings) else "no_high_risk_flag_detected_by_provider",
        "findings": findings,
        "report_fields_present": sorted(str(key) for key in report.keys()),
        "research_note": (
            "GoPlus reported one or more high-severity contract flags. Treat as a source-backed concern requiring a hold; "
            "the finding does not by itself prove malicious intent."
            if any(item["severity"] == "high" for item in findings)
            else "No configured high-severity flags were detected in this GoPlus report. This is not a global risk clearance; reputational and other security sources remain separate."
        ),
    })
    return result


def collect_security(payload: dict[str, Any], observed_at: str | None = None, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("prospect-review input must contain a records list")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    results = [research_security(record, timestamp, requester) for record in records]
    return {
        "schema_version": 1,
        "source": "GoPlus Token Security API",
        "source_coverage": {"supported_chain_names": sorted(CHAIN_IDS), "api_key_required": False, "attempts_per_request": MAX_ATTEMPTS, "timeout_seconds": TIMEOUT_SECONDS},
        "records_exported": len(results),
        "records_with_reports": sum(item["fetch_status"] == "success" for item in results),
        "records_with_high_risk_flags": sum(item["risk_status"] == "concern" for item in results),
        "records_without_reports": sum(item["fetch_status"] in {"no_report", "unsupported_chain", "missing_contract_address"} for item in results),
        "records_with_fetch_failures": sum(item["fetch_status"] in {"fetch_failed", "provider_error"} for item in results),
        "canonical_identity_or_risk_status_changed": False,
        "qualification_scores_changed": False,
        "outreach_enabled": False,
        "records": results,
        "note": "Provider-scoped observations only. No report or absence of configured flags is not proof of safety; canonical risk clearance remains unchanged.",
    }


def write_security(input_path: Path, output_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prospect-review input must be a JSON object")
    result = collect_security(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_exported", "records_with_reports", "records_with_high_risk_flags", "records_without_reports", "records_with_fetch_failures", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/security-research.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(write_security(args.input, args.output), indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
