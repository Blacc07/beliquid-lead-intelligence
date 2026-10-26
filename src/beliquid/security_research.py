"""Automated contract-risk observations from GoPlus Security API.

The adapter emits source-scoped observations only. A clean or missing GoPlus report is
not a global risk clearance, and this module never changes canonical identity/risk
reviews, qualification scores, dispositions, or outreach settings.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
API_ROOT = "https://api.gopluslabs.io/api/v1/token_security"
RUGCHECK_API_ROOT = "https://api.rugcheck.xyz/v1/tokens"
GOPLUS_SOLANA_API_ROOT = "https://api.gopluslabs.io/api/v1/solana/token_security"
HONEYPOT_API_ROOT = "https://api.honeypot.is/v2/IsHoneypot"
MAX_WORKERS = 6
SECURITY_CACHE_VERSION = 3
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
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    token = os.environ.get("GOPLUS_ACCESS_TOKEN", "").strip()
    if token and "api.gopluslabs.io" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
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



def fetch_token_report(url: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    """Fetch a RugCheck report with bounded retries for transient failures."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return requester(url)
        except HTTPError as exc:
            last_error = exc
            if exc.code == 404 or exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == MAX_ATTEMPTS - 1:
                raise
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS - 1:
                raise
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(0.25 * (2 ** attempt))
    if last_error:
        raise last_error
    raise RuntimeError("RugCheck request ended without a response")


def research_goplus_solana(record: dict[str, Any], observed_at: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    """Optional independent Solana security source; requires GOPLUS_ACCESS_TOKEN."""
    address = str(record.get("contract_address") or "").strip()
    url = f"{GOPLUS_SOLANA_API_ROOT}?{urlencode({'contract_addresses': address})}" if address else None
    result: dict[str, Any] = {"provider": "GoPlus Solana Token Security API", "provider_url": url,
        "observed_at": observed_at, "fetch_status": "not_attempted", "provider_report_status": "unknown",
        "risk_status": "unknown", "findings": []}
    if not address:
        result.update(fetch_status="missing_contract_address", research_note="No Solana mint supplied; GoPlus result remains unknown.")
        return result
    if requester is _default_request and not os.environ.get("GOPLUS_ACCESS_TOKEN", "").strip():
        result.update(fetch_status="credentials_missing", research_note="GOPLUS_ACCESS_TOKEN is not configured; the optional independent GoPlus Solana source was not called.")
        return result
    try:
        payload = fetch_token_report(url, requester)
    except HTTPError as exc:
        result.update(fetch_status="fetch_failed", research_note=f"GoPlus Solana returned HTTP {exc.code}; risk remains unknown.")
        return result
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result.update(fetch_status="fetch_failed", research_note=f"GoPlus Solana request failed ({type(exc).__name__}); risk remains unknown.")
        return result
    if payload.get("code") not in (None, 1, "1", 200, "200"):
        result.update(fetch_status="provider_error", research_note="GoPlus Solana returned an API error; risk remains unknown.")
        return result
    data = payload.get("result")
    report = (data.get(address) or data.get(address.casefold()) or data.get(address.upper())) if isinstance(data, dict) else None
    if not isinstance(report, dict) or not report:
        result.update(fetch_status="no_report", provider_report_status="not_found", research_note="GoPlus Solana returned no matching report; this is not evidence of safety.")
        return result
    findings = []
    for field in ("mint_authority", "freeze_authority", "close_authority", "metadata_mutable", "balance_mutable", "transfer_fee", "transfer_hook"):
        value = report.get(field)
        if value not in (None, "", False, "0", 0, "null"):
            findings.append({"field": field, "value": str(value)[:300], "severity": "review",
                             "description": "GoPlus Solana reports a token authority or mutable-token capability requiring context"})
    result.update({"fetch_status": "success", "provider_report_status": "found",
        "risk_status": "no_high_risk_flag_detected_by_provider",
        "findings": findings, "report_fields_present": sorted(str(key) for key in report),
        "research_note": "GoPlus Solana observations are source-scoped; authority and mutable-token fields require context and do not independently prove malicious behavior."})
    return result


def research_solana_security(record: dict[str, Any], observed_at: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    """Fetch a source-scoped RugCheck report for a Solana mint."""
    address = str(record.get("contract_address") or "").strip()
    url = f"{RUGCHECK_API_ROOT}/{quote(address, safe='')}/report" if address else None
    result: dict[str, Any] = {
        "project_name": record.get("project_name", ""), "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""), "provider": "RugCheck Solana Token Report", "cache_version": SECURITY_CACHE_VERSION,
        "provider_url": url, "observed_at": observed_at, "fetch_status": "not_attempted",
        "provider_report_status": "unknown", "risk_status": "unknown", "findings": [],
        "criterion_evidence_candidate": {"criterion": "security_and_reputational_integrity", "status": "unknown", "evidence_url": None, "observed_at": None},
        "outreach_enabled": False,
    }
    if not address:
        result.update(fetch_status="missing_contract_address", research_note="No Solana mint address supplied; risk remains unknown.")
        return result
    try:
        payload = fetch_token_report(url, requester)
    except HTTPError as exc:
        if exc.code == 404:
            result.update(fetch_status="no_report", provider_report_status="not_found", research_note="RugCheck returned no report; this is not evidence of safety.")
        else:
            result.update(fetch_status="fetch_failed", research_note=f"RugCheck request failed (HTTP {exc.code}); risk remains unknown.")
        return result
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result.update(fetch_status="fetch_failed", research_note=f"RugCheck request failed ({type(exc).__name__}); risk remains unknown.")
        return result
    report = payload.get("result") or payload.get("data") or payload
    if not isinstance(report, dict) or not report or not any(k in report for k in ("risks", "riskLevel", "risk_level", "token", "tokenMeta", "score")):
        result.update(fetch_status="no_report", provider_report_status="not_found", research_note="RugCheck returned no recognizable token report; this is not evidence of safety.")
        return result
    level = str(report.get("riskLevel") or report.get("risk_level") or "").strip().casefold()
    high_levels = {"danger", "dangerous", "critical", "scam", "risky", "high", "severe"}
    findings = []
    if report.get("rugged") is True:
        findings.append({"field": "rugged", "value": "true", "severity": "high", "description": "RugCheck reports the token as rugged"})
    if level in high_levels:
        findings.append({"field": "riskLevel", "value": level, "severity": "high", "description": "RugCheck reports a high-risk token classification"})
    risks = report.get("risks", [])
    if isinstance(risks, list):
        for item in risks:
            if not isinstance(item, dict):
                continue
            item_level = str(item.get("level") or item.get("severity") or "").strip().casefold()
            risk_text = f"{item.get('name') or ''} {item.get('description') or ''}".casefold()
            # Do not turn commercial-market weakness into a security hold merely
            # because the provider uses a severe label for a low-liquidity signal.
            explicit_security_concerns = (
                "rugged", "creator history of rug", "honeypot", "scam", "malicious",
                "large amount of lp unlocked", "lp unlocked", "mint authority still enabled",
                "freeze authority still enabled", "cannot sell", "hidden owner", "blacklist",
            )
            is_security_concern = any(term in risk_text for term in explicit_security_concerns)
            if is_security_concern and (item_level in high_levels or any(term in risk_text for term in explicit_security_concerns)):
                findings.append({"field": "risk_item", "value": str(item.get("name") or "provider risk item")[:300], "severity": "high", "description": str(item.get("description") or item.get("name") or "RugCheck high-severity risk item")[:1000]})
            elif item.get("name") or item.get("description"):
                findings.append({"field": "risk_item", "value": str(item.get("name") or item.get("description"))[:300], "severity": "review", "description": str(item.get("description") or item.get("name"))[:1000]})
    token = report.get("token") if isinstance(report.get("token"), dict) else {}
    for field, label in (("mintAuthority", "mint authority remains configured"), ("freezeAuthority", "freeze authority remains configured")):
        if token.get(field):
            findings.append({"field": field, "value": str(token[field])[:300], "severity": "review", "description": label})
    concern = any(item["severity"] == "high" for item in findings)
    result.update({
        "fetch_status": "success", "provider_report_status": "found",
        "risk_status": "concern" if concern else "no_high_risk_flag_detected_by_provider",
        "findings": findings, "provider_risk_level": report.get("riskLevel") or report.get("risk_level"),
        "provider_risk_score": report.get("score_normalised", report.get("score_normalized", report.get("score"))),
        "report_fields_present": sorted(str(key) for key in report.keys()),
        "criterion_evidence_candidate": {"criterion": "security_and_reputational_integrity", "status": "candidate_only", "source_scoped_risk_status": "concern" if concern else "no_high_risk_flag_detected_by_provider", "evidence_url": url, "observed_at": observed_at, "note": "A single Solana security report is not a complete security or reputational assessment."},
        "research_note": "RugCheck findings are source-scoped observations, not a global safety guarantee.",
    })
    return result


def research_honeypot_is(record: dict[str, Any], observed_at: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    """Fetch an independent EVM token simulation; unavailable data is never clean."""
    chain = str(record.get("chain") or "").strip().casefold()
    chain_id = CHAIN_IDS.get(chain)
    address = str(record.get("contract_address") or "").strip()
    result: dict[str, Any] = {"provider": "Honeypot.is token simulation", "provider_url": None,
        "observed_at": observed_at, "fetch_status": "not_attempted", "provider_report_status": "unknown",
        "risk_status": "unknown", "findings": []}
    if not chain_id:
        result.update(fetch_status="unsupported_chain", research_note="Honeypot.is chain mapping unavailable; independent source remains unknown.")
        return result
    if not address:
        result.update(fetch_status="missing_contract_address", research_note="No contract address supplied; independent source remains unknown.")
        return result
    url = f"{HONEYPOT_API_ROOT}?{urlencode({'address': address, 'chainID': chain_id})}"
    result["provider_url"] = url
    try:
        payload = fetch_token_report(url, requester)
    except HTTPError as exc:
        result.update(fetch_status="no_report" if exc.code == 404 else "fetch_failed",
                      provider_report_status="not_found" if exc.code == 404 else "unknown",
                      research_note=f"Honeypot.is request returned HTTP {exc.code}; this is not evidence of safety.")
        return result
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result.update(fetch_status="fetch_failed", research_note=f"Honeypot.is request failed ({type(exc).__name__}); independent risk remains unknown.")
        return result
    honeypot = payload.get("honeypotResult") if isinstance(payload.get("honeypotResult"), dict) else {}
    simulation = payload.get("simulationResult") if isinstance(payload.get("simulationResult"), dict) else {}
    if not honeypot and not simulation and not any(k in payload for k in ("contractCode", "token", "summary")):
        result.update(fetch_status="no_report", provider_report_status="not_found", research_note="Honeypot.is returned no recognizable simulation report; independent risk remains unknown.")
        return result
    findings = []
    if honeypot.get("isHoneypot") is True:
        findings.append({"field": "isHoneypot", "value": "true", "severity": "high", "description": "Honeypot.is simulation reports honeypot behavior"})
    for field in ("buyTax", "sellTax"):
        value = simulation.get(field)
        try:
            numeric = float(value) if value is not None else None
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None and numeric >= 20:
            findings.append({"field": field, "value": str(value), "severity": "review", "description": f"Honeypot.is simulation reports {field} at or above 20%; execution conditions matter"})
    result.update({"fetch_status": "success", "provider_report_status": "found",
        "risk_status": "concern" if any(item["severity"] == "high" for item in findings) else "no_high_risk_flag_detected_by_provider",
        "findings": findings,
        "simulation_summary": {key: simulation.get(key) for key in ("buyTax", "sellTax", "buyGas", "sellGas", "maxBuy", "maxSell") if key in simulation},
        "contract_code_summary": {key: payload.get("contractCode", {}).get(key) for key in ("openSource", "isProxy", "hasProxyCalls") if isinstance(payload.get("contractCode"), dict) and key in payload.get("contractCode", {})},
        "research_note": "Simulation results depend on provider support, chain state, and simulation conditions; this source does not establish global safety."})
    return result


def research_security(record: dict[str, Any], observed_at: str, requester: Callable[[str], dict[str, Any]] = _default_request) -> dict[str, Any]:
    chain = str(record.get("chain") or "").strip().casefold()
    address = str(record.get("contract_address") or "").strip()
    result: dict[str, Any] = {
        "project_name": record.get("project_name", ""),
        "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""),
        "provider": "GoPlus Token Security API", "cache_version": SECURITY_CACHE_VERSION,
        "provider_url": None,
        "observed_at": observed_at,
        "fetch_status": "not_attempted",
        "provider_report_status": "unknown",
        "risk_status": "unknown",
        "findings": [],
        "criterion_evidence_candidate": {"criterion": "security_and_reputational_integrity", "status": "unknown", "evidence_url": None, "observed_at": None},
        "outreach_enabled": False,
    }
    if chain in {"solana", "sol"}:
        primary = research_solana_security(record, observed_at, requester)
        secondary = research_goplus_solana(record, observed_at, requester)
        primary["independent_sources"] = [
            {"provider": primary.get("provider"), "provider_url": primary.get("provider_url"),
             "fetch_status": primary.get("fetch_status"), "risk_status": primary.get("risk_status"),
             "findings": primary.get("findings", []), "observed_at": primary.get("observed_at")},
            secondary,
        ]
        primary["independent_provider_count"] = sum(item.get("fetch_status") == "success" for item in primary["independent_sources"])
        if secondary.get("fetch_status") == "success":
            primary["independent_sources"][1]["risk_status"] = secondary.get("risk_status")
        if secondary.get("risk_status") == "concern":
            primary["risk_status"] = "concern"
            primary["findings"] = list(primary.get("findings", [])) + [
                {**item, "provider": secondary.get("provider")} for item in secondary.get("findings", []) if item.get("severity") == "high"
            ]
        primary["independent_coverage_note"] = "RugCheck is the default Solana source; GoPlus Solana coverage is attempted only when GOPLUS_ACCESS_TOKEN is configured. Missing credentials or reports remain unknown."
        return primary
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
    secondary = research_honeypot_is(record, observed_at, requester)
    secondary_findings = [{**item, "provider": "Honeypot.is token simulation"} for item in secondary.get("findings", [])]
    all_findings = findings + secondary_findings
    any_concern = any(item.get("severity") == "high" for item in all_findings)
    result.update({
        "fetch_status": "success",
        "provider_report_status": "found",
        "risk_status": "concern" if any_concern else "no_high_risk_flag_detected_by_provider",
        "findings": findings,
        "independent_sources": [
            {"provider": "GoPlus Token Security API", "provider_url": url, "fetch_status": "success",
             "risk_status": "concern" if any(item["severity"] == "high" for item in findings) else "no_high_risk_flag_detected_by_provider",
             "findings": findings, "observed_at": observed_at},
            secondary,
        ],
        "independent_provider_count": 2 if secondary.get("fetch_status") == "success" else 1,
        "criterion_evidence_candidate": {"criterion": "security_and_reputational_integrity", "status": "candidate_only", "source_scoped_risk_status": "concern" if any_concern else "no_high_risk_flag_detected_by_provider", "evidence_url": url, "observed_at": observed_at, "note": "Provider-specific findings are retained separately; unavailable secondary results do not imply safety."},
        "report_fields_present": sorted(str(key) for key in report.keys()),
        "research_note": (
            "At least one provider reported a high-severity contract concern. Route conservatively; this is source-backed evidence, not conclusive proof of malicious intent."
            if any_concern
            else "No configured high-severity flag was detected in the returned reports. Provider coverage may be incomplete; this is not global risk clearance."
        ),
    })
    return result


def _security_cache_fresh(observed_at: Any, ttl_hours: float, now: datetime) -> bool:
    if not isinstance(observed_at, str):
        return False
    try:
        stamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return False
    age = (now - stamp.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= ttl_hours * 3600


def collect_security(payload: dict[str, Any], observed_at: str | None = None, requester: Callable[[str], dict[str, Any]] = _default_request, previous_payload: dict[str, Any] | None = None, cache_ttl_hours: float = 24) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("prospect-review input must contain a records list")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    prior_records = previous_payload.get("records", []) if isinstance(previous_payload, dict) else []
    prior_by_key = {f"{str(item.get('chain') or '').casefold()}:{str(item.get('contract_address') or '').casefold()}": item for item in prior_records if isinstance(item, dict)}
    results = []
    reused = 0
    historical_retained = 0
    for record in records:
        key = f"{str(record.get('chain') or '').casefold()}:{str(record.get('contract_address') or '').casefold()}"
        prior = prior_by_key.get(key)
        canonical = record.get("identity_risk") or {}
        explicit_clear = canonical.get("identity_status") == "verified" and canonical.get("risk_status") == "clear"
        prior_concern = bool(prior and prior.get("risk_status") == "concern" and not explicit_clear)
        if prior and prior.get("cache_version") == SECURITY_CACHE_VERSION and prior.get("fetch_status") in {"success", "no_report"} and _security_cache_fresh(prior.get("observed_at"), cache_ttl_hours, now) and not (prior.get("risk_status") == "concern" and explicit_clear):
            item = dict(prior)
            item["reused_from_cache"] = True
            results.append(item)
            reused += 1
            continue
        current = research_security(record, timestamp, requester)
        current["reused_from_cache"] = False
        if prior_concern and current.get("risk_status") != "concern":
            prior_findings = prior.get("findings") if isinstance(prior.get("findings"), list) else []
            current_findings = current.get("findings") if isinstance(current.get("findings"), list) else []
            current.update({
                "risk_status": "concern",
                "historical_concern_retained": True,
                "prior_concern_observed_at": prior.get("observed_at"),
                "prior_concern_provider": prior.get("provider"),
                "criterion_evidence_candidate": {"criterion": "security_and_reputational_integrity", "status": "candidate_only", "source_scoped_risk_status": "concern", "evidence_url": prior.get("provider_url"), "observed_at": prior.get("observed_at"), "note": "A prior high-severity concern remains active until explicitly resolved."},
                "findings": prior_findings + current_findings,
                "research_note": "A prior high-severity concern is retained because the latest source result did not explicitly resolve it. A source outage or clean single-provider report does not silently clear a documented concern.",
            })
            historical_retained += 1
        results.append(current)
    return {
        "schema_version": 1,
        "source": "GoPlus plus Honeypot.is simulation (configured EVM chains); RugCheck (Solana)",
        "cache_version": SECURITY_CACHE_VERSION,
        "source_coverage": {"goplus_chain_names": sorted(CHAIN_IDS), "solana_provider": "RugCheck", "solana_secondary_provider": "GoPlus Solana (GOPLUS_ACCESS_TOKEN optional)", "evm_secondary_provider": "Honeypot.is", "api_key_required": False, "attempts_per_request": MAX_ATTEMPTS, "timeout_seconds": TIMEOUT_SECONDS, "max_workers": MAX_WORKERS, "cache_ttl_hours": cache_ttl_hours},
        "records_reused_from_cache": reused,
        "historical_concerns_retained": historical_retained,
        "records_exported": len(results),
        "records_with_reports": sum(item["fetch_status"] == "success" for item in results),
        "records_fetched_this_run": sum(item["fetch_status"] in {"success", "no_report"} and not item.get("reused_from_cache") for item in results),
        "records_with_high_risk_flags": sum(item["risk_status"] == "concern" for item in results),
        "records_without_reports": sum(item["fetch_status"] in {"no_report", "unsupported_chain", "missing_contract_address"} for item in results),
        "records_with_fetch_failures": sum(item["fetch_status"] in {"fetch_failed", "provider_error"} for item in results),
        "canonical_identity_or_risk_status_changed": False,
        "qualification_scores_changed": False,
        "outreach_enabled": False,
        "records": results,
        "note": "Provider-scoped observations only. No report or absence of configured flags is not proof of safety; canonical risk clearance remains unchanged.",
    }


def write_security(input_path: Path, output_path: Path, previous_path: Path | None = None, cache_ttl_hours: float = 24) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path and previous_path.is_file() else None
    if not isinstance(payload, dict):
        raise ValueError("prospect-review input must be a JSON object")
    result = collect_security(payload, previous_payload=previous, cache_ttl_hours=cache_ttl_hours)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_exported", "records_with_reports", "records_with_high_risk_flags", "records_without_reports", "records_with_fetch_failures", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/security-research.json"))
    parser.add_argument("--previous", type=Path, default=Path(".cache/research-state/security-research.json"))
    parser.add_argument("--cache-ttl-hours", type=float, default=24)
    args = parser.parse_args()
    try:
        print(json.dumps(write_security(args.input, args.output, args.previous, args.cache_ttl_hours), indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
