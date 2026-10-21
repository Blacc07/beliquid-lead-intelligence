"""Discover dated buying-trigger candidates from RSS/Atom feeds linked by project pages.

Feed entries are candidates only. This adapter never writes verified buying-trigger
reviews or qualification scores, and it preserves fetch failures and undated items.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET

from beliquid.automated_research import USER_AGENT, _SafeRedirect, _public_http_url

TIMEOUT_SECONDS = 8
MAX_BYTES = 1_000_000
MAX_FEEDS_PER_PROSPECT = 2
MAX_ENTRIES_PER_FEED = 100
MAX_WORKERS = 6
TRIGGER_TERMS = {
    "exchange_listing": ("listing", "listed on", "exchange listing", "new trading pair", "trading pair"),
    "token_launch_or_tge": ("launch", "mainnet", "token generation", "tge", "token launch"),
    "milestone_or_campaign": ("fundraising", "raised", "funding round", "partnership", "integrat"),
    "venue_expansion": ("venue expansion", "new exchange", "market expansion"),
    "documented_liquidity_issue": ("liquidity issue", "market maker", "market making", "liquidity provider"),
    "milestone_or_campaign": ("milestone", "campaign", "incentive", "ecosystem"),
    "token_unlock": ("token unlock", "unlock schedule", "vesting"),
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _text(parent: ET.Element, names: set[str]) -> str:
    for child in list(parent):
        if _local_name(child.tag) in names:
            value = " ".join("".join(child.itertext()).split())
            if value:
                return value[:4000]
    return ""


def _entry_link(entry: ET.Element) -> str:
    for child in list(entry):
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
            value = " ".join("".join(child.itertext()).split())
            if value:
                return value
    return ""


def _parse_timestamp(value: str) -> str | None:
    if not value.strip():
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def fetch_feed(url: str) -> dict[str, Any]:
    safe_url = _public_http_url(url)
    if safe_url is None:
        raise ValueError("feed URL must be a public HTTP(S) URL")
    client = build_opener(_SafeRedirect())
    request = Request(safe_url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml,application/rss+xml,application/xml,text/xml"})
    with client.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        if _public_http_url(final_url) is None:
            raise ValueError("final feed URL is not public")
        content_type = response.headers.get("Content-Type", "").casefold()
        if not any(value in content_type for value in ("xml", "rss", "atom")):
            raise ValueError("feed response is not XML/RSS/Atom")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("feed response exceeded 1 MB limit")
    root = ET.fromstring(body)
    entries = []
    for node in root.iter():
        if _local_name(node.tag) not in {"item", "entry"}:
            continue
        title = _text(node, {"title"})
        summary = _text(node, {"description", "summary", "content", "encoded"})
        link = _entry_link(node)
        published = _text(node, {"pubdate", "published", "updated", "date", "issued"})
        entries.append({"title": title, "summary": summary, "url": urljoin(final_url, link) if link else final_url, "published_at": _parse_timestamp(published)})
        if len(entries) >= MAX_ENTRIES_PER_FEED:
            break
    return {"feed_url": final_url, "content_type": content_type, "entries": entries}


def _classify_trigger(text: str) -> str | None:
    lowered = text.casefold()
    for trigger_type, terms in TRIGGER_TERMS.items():
        if any(term in lowered for term in terms):
            return trigger_type
    return None


def research_feed(record: dict[str, Any], feed_url: str, observed_at: str, fetcher=fetch_feed) -> dict[str, Any]:
    base = {
        "project_name": record.get("project_name", ""),
        "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""),
        "feed_url": feed_url,
        "observed_at": observed_at,
        "fetch_status": "not_attempted",
        "entries_checked": 0,
        "trigger_candidates": [],
        "outreach_enabled": False,
    }
    try:
        feed = fetcher(feed_url)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
        base.update(fetch_status="fetch_failed", error_type=type(exc).__name__)
        return base

    name = str(record.get("project_name") or "").strip().casefold()
    symbol = str(record.get("token_symbol") or "").strip().casefold()
    contract = str(record.get("contract_address") or "").strip().casefold()
    entities = [value for value in (name, symbol, contract) if len(value) >= 4]
    candidates = []
    for entry in feed.get("entries", [])[:MAX_ENTRIES_PER_FEED]:
        title = str(entry.get("title") or "")
        summary = str(entry.get("summary") or "")
        text = f"{title} {summary}".strip()
        lowered = text.casefold()
        if not entities or not any(entity in lowered for entity in entities):
            continue
        trigger_type = _classify_trigger(text)
        if not trigger_type:
            continue
        event_url = urljoin(feed.get("feed_url") or feed_url, str(entry.get("url") or ""))
        parsed_url = urlparse(event_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        candidates.append({
            "trigger_type": trigger_type,
            "status": "candidate_only",
            "title": title[:500],
            "summary_excerpt": summary[:1000],
            "event_url": event_url,
            "feed_url": feed.get("feed_url") or feed_url,
            "published_at": entry.get("published_at"),
            "observed_at": observed_at,
            "date_verified": bool(entry.get("published_at")),
            "note": "Feed item matched project metadata and a trigger term; event attribution/date still require corroboration.",
        })
    base.update(
        fetch_status="success",
        final_feed_url=feed.get("feed_url") or feed_url,
        entries_checked=len(feed.get("entries", [])),
        trigger_candidates=candidates,
        research_note="Dated feed matches are source-backed candidates only; they do not create verified buying-trigger reviews.",
    )
    return base


def collect_trigger_research(prospect_payload: dict[str, Any], public_research: dict[str, Any], observed_at: str | None = None, fetcher=fetch_feed) -> dict[str, Any]:
    prospects = prospect_payload.get("records")
    public_records = public_research.get("records")
    if not isinstance(prospects, list) or not isinstance(public_records, list):
        raise ValueError("prospect and public research inputs must contain records lists")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    prospect_map = {f"{str(r.get('chain') or '').casefold()}:{str(r.get('contract_address') or '').casefold()}": r for r in prospects if isinstance(r, dict)}
    jobs = []
    for public in public_records:
        if not isinstance(public, dict):
            continue
        key = f"{str(public.get('chain') or '').casefold()}:{str(public.get('contract_address') or '').casefold()}"
        prospect = prospect_map.get(key)
        if not prospect:
            continue
        feeds = public.get("feed_candidates") or []
        for feed in feeds[:MAX_FEEDS_PER_PROSPECT]:
            if isinstance(feed, dict) and isinstance(feed.get("url"), str):
                jobs.append((prospect, feed["url"]))
    def run(job):
        return research_feed(job[0], job[1], timestamp, fetcher)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        feed_results = list(pool.map(run, jobs))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in feed_results:
        key = f"{str(result.get('chain') or '').casefold()}:{str(result.get('contract_address') or '').casefold()}"
        grouped.setdefault(key, []).append(result)
    records = []
    for prospect in prospects:
        if not isinstance(prospect, dict):
            continue
        key = f"{str(prospect.get('chain') or '').casefold()}:{str(prospect.get('contract_address') or '').casefold()}"
        feeds = grouped.get(key, [])
        records.append({
            "project_name": prospect.get("project_name", ""),
            "chain": prospect.get("chain", ""),
            "contract_address": prospect.get("contract_address", ""),
            "feeds_attempted": len(feeds),
            "feeds_succeeded": sum(item["fetch_status"] == "success" for item in feeds),
            "feeds_failed": sum(item["fetch_status"] == "fetch_failed" for item in feeds),
            "trigger_candidates": [candidate for item in feeds for candidate in item["trigger_candidates"]],
            "feed_results": feeds,
            "buying_trigger_status": "unknown",
            "outreach_enabled": False,
        })
    return {
        "schema_version": 1,
        "source": "RSS/Atom feeds linked from candidate project websites",
        "records_exported": len(records),
        "feeds_attempted": len(feed_results),
        "feeds_succeeded": sum(item["fetch_status"] == "success" for item in feed_results),
        "feeds_failed": sum(item["fetch_status"] == "fetch_failed" for item in feed_results),
        "trigger_candidates": sum(len(item["trigger_candidates"]) for item in feed_results),
        "verified_triggers_created": 0,
        "canonical_buying_trigger_reviews_changed": False,
        "qualification_scores_changed": False,
        "outreach_enabled": False,
        "records": records,
    }


def write_trigger_research(prospect_path: Path, public_path: Path, output_path: Path) -> dict[str, Any]:
    prospect = json.loads(prospect_path.read_text(encoding="utf-8"))
    public = json.loads(public_path.read_text(encoding="utf-8"))
    result = collect_trigger_research(prospect, public)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_exported", "feeds_attempted", "feeds_succeeded", "feeds_failed", "trigger_candidates", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--public-research", type=Path, default=Path("artifacts/automated-research.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/trigger-research.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(write_trigger_research(args.input, args.public_research, args.output), indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
