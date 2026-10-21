"""Token-name and market-metric enrichment via the documented DEX Screener API."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from http.client import HTTPException
import json
import logging
import math
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

from beliquid.models import Evidence, ProspectRecord
from beliquid.sources.dexscreener import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    USER_AGENT,
    DexScreenerError,
    DexScreenerHTTPError,
    DexScreenerRateLimitError,
    DexScreenerResponseError,
    DexScreenerUnavailableError,
    Transport,
    _default_transport,
    fetch_latest_profiles,
)

LOGGER = logging.getLogger(__name__)
TOKENS_URL = "https://api.dexscreener.com/tokens/v1"
MAX_ADDRESSES_PER_REQUEST = 30
_METRIC_KEYS = (
    "price_usd",
    "liquidity_usd",
    "volume_24h_usd",
    "market_cap_usd",
    "fdv_usd",
    "txns_24h_buys",
    "txns_24h_sells",
    "pool_count",
)


def _number(value: Any) -> float | None:
    """Parse a finite, non-negative numeric API value; unknown stays None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _address_key(chain: str, address: str) -> tuple[str, str]:
    return chain.strip().casefold(), address.strip().casefold()


def _pair_token(pair: dict[str, Any], address: str) -> dict[str, Any] | None:
    """Return the token object matching this address, not an unrelated pair side."""
    for field in ("baseToken", "quoteToken"):
        token = pair.get(field)
        if isinstance(token, dict):
            token_address = token.get("address")
            if isinstance(token_address, str) and token_address.casefold() == address.casefold():
                return token
    return None


def _pair_liquidity(pair: dict[str, Any]) -> float:
    liquidity = pair.get("liquidity")
    value = _number(liquidity.get("usd")) if isinstance(liquidity, dict) else None
    return value if value is not None else -1.0


def _safe_pair_url(pair: dict[str, Any]) -> str | None:
    value = pair.get("url")
    if not isinstance(value, str) or not value.strip():
        return None
    from urllib.parse import urlparse

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value.strip()


def _pair_metrics(pair: dict[str, Any], pool_count: int) -> dict[str, float | int | None]:
    liquidity = pair.get("liquidity")
    volume = pair.get("volume")
    transactions = pair.get("txns")
    h24_volume = volume.get("h24") if isinstance(volume, dict) else None
    h24_transactions = transactions.get("h24") if isinstance(transactions, dict) else None
    buys = h24_transactions.get("buys") if isinstance(h24_transactions, dict) else None
    sells = h24_transactions.get("sells") if isinstance(h24_transactions, dict) else None
    return {
        "price_usd": _number(pair.get("priceUsd")),
        "liquidity_usd": _number(liquidity.get("usd")) if isinstance(liquidity, dict) else None,
        "volume_24h_usd": _number(h24_volume),
        "market_cap_usd": _number(pair.get("marketCap")),
        "fdv_usd": _number(pair.get("fdv")),
        "txns_24h_buys": _number(buys),
        "txns_24h_sells": _number(sells),
        "pool_count": pool_count,
    }


def fetch_token_pairs(
    chain: str,
    addresses: list[str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Transport = _default_transport,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch pools for up to 30 addresses on one chain, using one API request."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    clean_addresses = [address.strip() for address in addresses if isinstance(address, str) and address.strip()]
    if not chain.strip() or not clean_addresses:
        raise ValueError("chain and at least one token address are required")
    if len(clean_addresses) > MAX_ADDRESSES_PER_REQUEST:
        raise ValueError("a DEX Screener token lookup supports at most 30 addresses per request")

    encoded_chain = quote(chain.strip(), safe="")
    encoded_addresses = ",".join(quote(address, safe="") for address in clean_addresses)
    url = f"{TOKENS_URL}/{encoded_chain}/{encoded_addresses}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET")
    try:
        body = transport(request, timeout)
    except HTTPError as exc:
        if exc.code == 429:
            raise DexScreenerRateLimitError(
                "DEX Screener token lookup rate limit reached (HTTP 429); wait before retrying."
            ) from exc
        raise DexScreenerHTTPError(f"DEX Screener token lookup returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise DexScreenerUnavailableError(
            f"Could not reach DEX Screener token lookup ({type(exc).__name__})."
        ) from exc

    if len(body) > MAX_RESPONSE_BYTES:
        raise DexScreenerResponseError("DEX Screener token lookup exceeded the 2 MB safety limit")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DexScreenerResponseError("DEX Screener token lookup returned invalid JSON") from exc
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise DexScreenerResponseError("Expected token lookup response to be an array of pair objects")
    return payload, url


def _enrich_one(
    record: ProspectRecord,
    pairs: list[dict[str, Any]],
    source_url: str,
    observed_at: str,
) -> ProspectRecord:
    matching = [
        pair for pair in pairs
        if _pair_token(pair, record.contract_address or "") is not None
    ]
    matching.sort(key=_pair_liquidity, reverse=True)
    best = matching[0] if matching else None
    token = _pair_token(best, record.contract_address or "") if best else None
    name = token.get("name") if isinstance(token, dict) else None
    symbol = token.get("symbol") if isinstance(token, dict) else None
    project_name = name.strip() if isinstance(name, str) and name.strip() else record.project_name
    token_symbol = symbol.strip() if isinstance(symbol, str) and symbol.strip() else record.token_symbol
    metrics = dict(record.metrics)
    metrics.update({key: None for key in _METRIC_KEYS})
    if best is not None:
        metrics.update(_pair_metrics(best, len(matching)))
        evidence_url = _safe_pair_url(best) or source_url
        notes = (
            f"Token name/symbol and metrics matched by contract address. "
            f"Metrics describe the highest-liquidity pool among {len(matching)} matching pool(s); "
            "they are not totals across pools. Market data is volatile and not a quality score."
        )
    else:
        metrics["pool_count"] = 0
        evidence_url = source_url
        notes = "Lookup succeeded but returned no matching pools; market metrics remain unknown."

    evidence = record.evidence + (
        Evidence(
            source_name="DEX Screener",
            source_url=evidence_url,
            observed_at=observed_at,
            evidence_type="token_market_enrichment",
            notes=notes,
        ),
    )
    return ProspectRecord(
        project_name=project_name,
        chain=record.chain,
        contract_address=record.contract_address,
        website_url=record.website_url,
        token_symbol=token_symbol,
        metrics=metrics,
        evidence=evidence,
    )


def enrich_records(
    records: list[ProspectRecord],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Transport = _default_transport,
    observed_at: str | None = None,
) -> tuple[list[ProspectRecord], dict[str, Any]]:
    """Enrich records in chain-grouped batches; failed batches remain explicitly unknown."""
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    enriched_by_key = {record.dedupe_key: record for record in records}
    grouped: dict[str, list[ProspectRecord]] = defaultdict(list)
    for record in records:
        if record.contract_address:
            grouped[record.chain].append(record)

    batch_count = 0
    batches_succeeded = 0
    failures: list[dict[str, str]] = []
    for chain, chain_records in grouped.items():
        for offset in range(0, len(chain_records), MAX_ADDRESSES_PER_REQUEST):
            batch = chain_records[offset:offset + MAX_ADDRESSES_PER_REQUEST]
            addresses = [record.contract_address for record in batch if record.contract_address]
            batch_count += 1
            try:
                pairs, source_url = fetch_token_pairs(chain, addresses, timeout=timeout, transport=transport)
            except (DexScreenerError, ValueError) as exc:
                LOGGER.warning("Token enrichment failed for chain %s batch: %s", chain, exc)
                failures.append({"chain": chain, "error": str(exc)})
                continue
            batches_succeeded += 1
            for record in batch:
                enriched_by_key[record.dedupe_key] = _enrich_one(record, pairs, source_url, timestamp)

    enriched = [enriched_by_key[record.dedupe_key] for record in records]
    records_with_market_data = sum(
        1 for record in enriched
        if any(record.metrics.get(key) is not None for key in _METRIC_KEYS if key != "pool_count")
    )
    status = "success" if not failures else ("partial_success" if batches_succeeded else "failure")
    summary = {
        "source": "DEX Screener",
        "status": status,
        "records_discovered": len(records),
        "records_with_market_data": records_with_market_data,
        "batches_attempted": batch_count,
        "batches_succeeded": batches_succeeded,
        "batch_failures": failures,
        "note": (
            "Metrics describe each token's highest-liquidity matching pool, not totals across pools. "
            "Missing data remains unknown; discovery and market metrics are not a lead-quality score."
        ),
        "sample": [
            {
                "chain": record.chain,
                "token_address": record.contract_address,
                "token_name": record.project_name,
                "token_symbol": record.token_symbol,
                "price_usd": record.metrics.get("price_usd"),
                "liquidity_usd": record.metrics.get("liquidity_usd"),
                "volume_24h_usd": record.metrics.get("volume_24h_usd"),
                "market_cap_usd": record.metrics.get("market_cap_usd"),
                "fdv_usd": record.metrics.get("fdv_usd"),
                "pool_count": record.metrics.get("pool_count"),
                "evidence_url": record.evidence[-1].source_url if len(record.evidence) > 1 else None,
            }
            for record in enriched[:5]
        ],
    }
    return enriched, summary


def main() -> int:
    """Discover current profiles, enrich token data, and print a bounded summary."""
    try:
        records = fetch_latest_profiles()
        _enriched, summary = enrich_records(records)
    except DexScreenerError as exc:
        print(json.dumps({"source": "DEX Screener", "status": "failure", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(summary, sort_keys=True))
    if summary["status"] == "failure" and summary["batches_attempted"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
