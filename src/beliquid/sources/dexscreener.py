"""DEX Screener public API adapter.

This adapter uses the documented latest token profiles endpoint. That feed is a
discovery signal, not an endorsement or a measure of project quality.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http.client import HTTPException
import json
import logging
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from beliquid.models import Evidence, ProspectRecord

LOGGER = logging.getLogger(__name__)
API_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
USER_AGENT = "BeLiquid-Lead-Intelligence/0.1 (+https://github.com/Blacc07/beliquid-lead-intelligence)"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 2_000_000


class DexScreenerError(RuntimeError):
    """Base class for expected DEX Screener adapter failures."""


class DexScreenerRateLimitError(DexScreenerError):
    """Raised when the API returns HTTP 429."""


class DexScreenerHTTPError(DexScreenerError):
    """Raised when the API returns an unsuccessful HTTP status."""


class DexScreenerUnavailableError(DexScreenerError):
    """Raised when the API cannot be reached."""


class DexScreenerResponseError(DexScreenerError):
    """Raised when the API response cannot be parsed or validated."""


Transport = Callable[[Request, float], bytes]


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise DexScreenerHTTPError(f"DEX Screener returned HTTP {status}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise DexScreenerResponseError("DEX Screener response exceeded the 2 MB safety limit")
    return body


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _official_website(links: Any) -> str | None:
    """Return a URL explicitly labelled as a website; do not guess from social links."""
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        kind = str(link.get("type") or "").strip().casefold()
        label = str(link.get("label") or "").strip().casefold()
        url = link.get("url")
        if (kind == "website" or label in {"website", "official website", "site"}) and _is_http_url(url):
            return url.strip()
    return None


def normalize_profiles(payload: Any, observed_at: str | None = None) -> list[ProspectRecord]:
    """Validate and normalize latest-profile JSON into prospect records."""
    if not isinstance(payload, list):
        raise DexScreenerResponseError("Expected the latest token profiles response to be a JSON array")

    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    records: list[ProspectRecord] = []
    seen: set[str] = set()

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            LOGGER.warning("Skipping malformed DEX Screener profile at index %s: expected object", index)
            continue

        chain = item.get("chainId")
        address = item.get("tokenAddress")
        if not isinstance(chain, str) or not chain.strip() or not isinstance(address, str) or not address.strip():
            LOGGER.warning("Skipping DEX Screener profile at index %s: missing chainId or tokenAddress", index)
            continue

        source_url = item.get("url")
        if not _is_http_url(source_url):
            source_url = API_URL

        description = item.get("description")
        notes = description.strip()[:500] if isinstance(description, str) and description.strip() else (
            "Listed in DEX Screener's latest token profile feed; this is a discovery signal, not a quality rating."
        )

        try:
            record = ProspectRecord(
                # This endpoint does not guarantee a token name. Keep the address as an
                # explicit placeholder until a later enrichment step resolves the name.
                project_name=address.strip(),
                chain=chain.strip(),
                contract_address=address.strip(),
                website_url=_official_website(item.get("links")),
                metrics={},
                evidence=(
                    Evidence(
                        source_name="DEX Screener",
                        source_url=source_url.strip(),
                        observed_at=timestamp,
                        evidence_type="token_profile_discovery",
                        notes=notes,
                    ),
                ),
            )
        except (TypeError, ValueError) as exc:
            LOGGER.warning("Skipping invalid DEX Screener profile at index %s: %s", index, exc)
            continue

        if record.dedupe_key not in seen:
            seen.add(record.dedupe_key)
            records.append(record)

    return records


def fetch_latest_profiles(
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Transport = _default_transport,
) -> list[ProspectRecord]:
    """Fetch and normalize latest profiles with bounded timeout and response size."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    request = Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )

    try:
        body = transport(request, timeout)
    except HTTPError as exc:
        if exc.code == 429:
            raise DexScreenerRateLimitError(
                "DEX Screener rate limit reached (HTTP 429); wait before retrying."
            ) from exc
        raise DexScreenerHTTPError(f"DEX Screener returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise DexScreenerUnavailableError(
            f"Could not reach DEX Screener ({type(exc).__name__})."
        ) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DexScreenerResponseError("DEX Screener returned invalid JSON") from exc

    return normalize_profiles(payload)


def main() -> int:
    """Run a small discovery smoke test and print a privacy-conscious summary."""
    try:
        records = fetch_latest_profiles()
    except DexScreenerError as exc:
        print(json.dumps({"source": "DEX Screener", "status": "failure", "error": str(exc)}))
        return 1

    print(json.dumps({
        "source": "DEX Screener",
        "status": "success",
        "records_discovered": len(records),
        "note": "Latest profile feed is a discovery signal, not a quality rating; names and metrics may need enrichment.",
        "sample": [
            {
                "chain": record.chain,
                "token_address": record.contract_address,
                "website_url": record.website_url,
                "evidence_url": record.evidence[0].source_url,
            }
            for record in records[:5]
        ],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
