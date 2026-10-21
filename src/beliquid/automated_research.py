"""Collect bounded public-web evidence candidates without auto-clearing identity or risk.

This adapter gathers homepage metadata and source links from the candidate website already
present in the prospect export. Extracted statements are leads for further research, not
verified findings or qualification statuses.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import logging
import socket
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
USER_AGENT = "BeLiquid-Lead-Intelligence/0.1 (+https://github.com/Blacc07/beliquid-lead-intelligence)"
MAX_BYTES = 1_000_000
TIMEOUT_SECONDS = 8
MAX_LINKS = 40
MAX_TEXT = 20_000
TRIGGER_TERMS = (
    "launch", "listing", "mainnet", "testnet", "token generation", "tge",
    "liquidity", "market maker", "exchange", "trading pair", "partnership",
    "integrat", "incentive", "campaign", "roadmap",
)


def _public_http_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return None
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        except (OSError, ValueError):
            return None
    if not addresses or any(not address.is_global for address in addresses):
        return None
    return value.strip()


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        if _public_http_url(target) is None:
            raise ValueError("redirect target is not a public HTTP(S) URL")
        return super().redirect_request(req, fp, code, msg, headers, target)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.description = ""
        self.links: list[dict[str, str]] = []
        self.feed_links: list[str] = []
        self.text_parts: list[str] = []
        self._meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(k).casefold(): str(v) for k, v in attrs if k and v is not None}
        if tag.casefold() == "title":
            self.in_title = True
        if tag.casefold() == "meta":
            name = values.get("name", "").casefold()
            prop = values.get("property", "").casefold()
            if name == "description" or prop in {"og:description", "og:title", "og:site_name"}:
                key = name or prop
                if values.get("content"):
                    self._meta[key] = values["content"][:1000]
        if tag.casefold() == "link" and values.get("href"):
            rel = set(values.get("rel", "").casefold().split())
            kind = values.get("type", "").casefold()
            if "alternate" in rel and ("rss" in kind or "atom" in kind or "xml" in kind) and len(self.feed_links) < 10:
                self.feed_links.append(values["href"][:2000])
        if tag.casefold() == "a" and values.get("href") and len(self.links) < MAX_LINKS:
            self.links.append({"href": values["href"][:2000], "text": ""})

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if sum(len(part) for part in self.text_parts) < MAX_TEXT:
            self.text_parts.append(text)
        if self.links and not self.links[-1]["text"]:
            self.links[-1]["text"] = text[:300]

    def result(self) -> dict[str, Any]:
        self.description = self._meta.get("description") or self._meta.get("og:description", "")
        return {
            "page_title": " ".join(self.title_parts)[:500],
            "meta_description": self.description[:1000],
            "og_site_name": self._meta.get("og:site_name", "")[:300],
            "text_excerpt": " ".join(self.text_parts)[:MAX_TEXT],
            "links": self.links,
            "feed_links": self.feed_links,
        }


def fetch_page(url: str, timeout: float = TIMEOUT_SECONDS, opener=None) -> dict[str, Any]:
    """Fetch one public HTML page with byte, timeout, and redirect limits."""
    safe_url = _public_http_url(url)
    if safe_url is None:
        raise ValueError("candidate website must be a public HTTP(S) URL")
    client = opener or build_opener(_SafeRedirect())
    request = Request(safe_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with client.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        if _public_http_url(final_url) is None:
            raise ValueError("final page URL is not public")
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.casefold():
            raise ValueError("candidate website response is not HTML")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("candidate website page exceeds 1 MB limit")
    parser = _PageParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    result = parser.result()
    result["final_url"] = final_url
    result["content_type"] = content_type
    return result



def _record_fingerprint(record: dict[str, Any]) -> str:
    stable = {name: record.get(name) for name in ("project_name", "token_symbol", "chain", "contract_address", "website_url_candidate")}
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _within_cache_ttl(observed_at: Any, ttl_hours: float, now: datetime) -> bool:
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


def research_record(record: dict[str, Any], observed_at: str, fetcher: Callable[[str], dict[str, Any]] = fetch_page) -> dict[str, Any]:
    candidate = record.get("website_url_candidate")
    output: dict[str, Any] = {
        "project_name": record.get("project_name", ""),
        "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""),
        "input_fingerprint": _record_fingerprint(record),
        "reused_from_cache": False,
        "candidate_website_url": candidate,
        "observed_at": observed_at,
        "fetch_status": "not_attempted",
        "page": None,
        "source_candidates": [],
        "feed_candidates": [],
        "trigger_candidates": [],
        "criterion_evidence_candidates": [],
        "identity_status": "unknown",
        "risk_status": "unknown",
        "qualification_status": "not_assessed",
        "outreach_enabled": False,
    }
    if not candidate:
        output["fetch_status"] = "no_website_candidate"
        output["research_note"] = "No candidate website URL was available; identity and risk remain unknown."
        return output
    try:
        page = fetcher(candidate)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        output["fetch_status"] = "fetch_failed"
        output["research_note"] = f"Public-page collection failed ({type(exc).__name__}); identity and risk remain unknown."
        return output

    final_url = page.get("final_url") or candidate
    parsed = urlparse(final_url)
    links = []
    for link in page.get("links", []):
        href = link.get("href", "")
        absolute = urljoin(final_url, href)
        p = urlparse(absolute)
        if p.scheme in {"http", "https"} and p.netloc:
            links.append({"url": absolute, "label": link.get("text", "")[:300]})
    feed_candidates = []
    for feed_url in page.get("feed_links", []):
        absolute_feed = urljoin(final_url, str(feed_url))
        if _public_http_url(absolute_feed) and absolute_feed not in {item["url"] for item in feed_candidates}:
            feed_candidates.append({"url": absolute_feed, "source_type": "candidate_project_feed", "observed_at": observed_at})
    page_text = str(page.get("text_excerpt", ""))
    lowered = page_text.casefold()
    triggers = []
    for term in TRIGGER_TERMS:
        matches = [match.start() for match in re.finditer(re.escape(term), lowered)]
        if matches:
            excerpt = page_text[max(0, matches[0]-120):min(len(page_text), matches[0]+240)].strip()
            triggers.append({"term": term, "status": "candidate_only", "excerpt": excerpt, "evidence_url": final_url, "observed_at": observed_at})
    contract = str(record.get("contract_address") or "").strip()
    contract_mentioned = bool(contract and contract.casefold() in page_text.casefold())
    output.update({
        "fetch_status": "success",
        "page": {
            "final_url": final_url,
            "host": parsed.hostname,
            "page_title": page.get("page_title", ""),
            "meta_description": page.get("meta_description", ""),
            "og_site_name": page.get("og_site_name", ""),
            "text_excerpt": page_text[:MAX_TEXT],
            "contract_address_mentioned": contract_mentioned,
        },
        "source_candidates": [{"url": final_url, "source_type": "candidate_project_website", "observed_at": observed_at}]
            + [{"url": item["url"], "source_type": "outbound_link_candidate", "label": item["label"], "observed_at": observed_at} for item in links],
        "feed_candidates": feed_candidates,
        "trigger_candidates": triggers,
        "criterion_evidence_candidates": [
            {"criterion": "project_credibility_and_team_access", "candidate_type": "contract_address_mentioned_on_candidate_website", "status": "candidate_only", "observed": contract_mentioned, "evidence_url": final_url, "observed_at": observed_at},
            {"criterion": "service_fit_and_demonstrated_need", "candidate_type": "market_making_or_liquidity_language", "status": "candidate_only", "observed": any(term in lowered for term in ("market maker", "market making", "liquidity provider", "liquidity")), "evidence_url": final_url, "observed_at": observed_at},
            {"criterion": "growth_and_strategic_potential", "candidate_type": "development_or_partnership_language", "status": "candidate_only", "observed": any(term in lowered for term in ("roadmap", "partnership", "integration", "ecosystem")), "evidence_url": final_url, "observed_at": observed_at},
            {"criterion": "buying_trigger_and_timing", "candidate_type": "undated_homepage_trigger_keyword_match", "status": "candidate_only", "observed": bool(triggers), "matches": [item["term"] for item in triggers], "evidence_url": final_url, "observed_at": observed_at, "note": "Homepage keyword matches are not dated or verified buying triggers."},
            {"criterion": "market_activity_and_commercial_potential", "candidate_type": "timestamped_dex_screener_market_observation", "status": "candidate_only", "observed": any((record.get("metrics") or {}).get(name) is not None for name in ("volume_24h_usd", "liquidity_usd", "market_cap_usd", "fdv_usd")), "metrics": {name: (record.get("metrics") or {}).get(name) for name in ("volume_24h_usd", "liquidity_usd", "market_cap_usd", "fdv_usd")}, "evidence_url": next((item.get("source_url") for item in record.get("evidence", []) if isinstance(item, dict) and item.get("evidence_type") == "token_market_enrichment"), None), "observed_at": next((item.get("observed_at") for item in record.get("evidence", []) if isinstance(item, dict) and item.get("evidence_type") == "token_market_enrichment"), None), "note": "Market observations are not buying intent and do not auto-confirm this criterion."},
        ],
        "research_note": "Page text and keyword matches are candidate evidence only. They do not verify official identity, establish a clear risk status, confirm buying intent, or change criterion scores.",
    })
    return output


def collect_research(payload: dict[str, Any], observed_at: str | None = None, fetcher: Callable[[str], dict[str, Any]] = fetch_page, previous_payload: dict[str, Any] | None = None, cache_ttl_hours: float = 24) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("prospect-review input must contain a records list")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    previous_records = previous_payload.get("records", []) if isinstance(previous_payload, dict) else []
    previous_by_key = {f"{str(item.get('chain') or '').casefold()}:{str(item.get('contract_address') or '').casefold()}": item for item in previous_records if isinstance(item, dict)}
    results = []
    for record in records:
        key = f"{str(record.get('chain') or '').casefold()}:{str(record.get('contract_address') or '').casefold()}"
        cached = previous_by_key.get(key)
        fingerprint = _record_fingerprint(record)
        if (cached and cached.get("input_fingerprint") == fingerprint
                and cached.get("fetch_status") in {"success", "no_website_candidate"}
                and _within_cache_ttl(cached.get("observed_at"), cache_ttl_hours, now)):
            reused = dict(cached)
            reused["reused_from_cache"] = True
            results.append(reused)
        else:
            results.append(research_record(record, timestamp, fetcher))
    return {
        "schema_version": 1,
        "source": "candidate public project websites",
        "records_exported": len(results),
        "records_with_page_fetched": sum(item["fetch_status"] == "success" for item in results),
        "records_without_website_candidate": sum(item["fetch_status"] == "no_website_candidate" for item in results),
        "records_with_fetch_failures": sum(item["fetch_status"] == "fetch_failed" for item in results),
        "records_reused_from_cache": sum(bool(item.get("reused_from_cache")) for item in results),
        "cache_ttl_hours": cache_ttl_hours,
        "identity_or_risk_status_changed": False,
        "qualification_scores_changed": False,
        "outreach_enabled": False,
        "records": results,
        "note": "Candidate evidence collection only; no statuses or scores are inferred from page presence or keyword matches.",
    }


def write_research(input_path: Path, output_path: Path, previous_path: Path | None = None, cache_ttl_hours: float = 24) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path and previous_path.is_file() else None
    if not isinstance(payload, dict):
        raise ValueError("prospect-review input must be a JSON object")
    result = collect_research(payload, previous_payload=previous, cache_ttl_hours=cache_ttl_hours)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_exported", "records_with_page_fetched", "records_without_website_candidate", "records_with_fetch_failures", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/automated-research.json"))
    parser.add_argument("--previous", type=Path, default=Path(".cache/research-state/automated-research.json"))
    parser.add_argument("--cache-ttl-hours", type=float, default=24)
    args = parser.parse_args()
    try:
        print(json.dumps(write_research(args.input, args.output, args.previous, args.cache_ttl_hours), indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
