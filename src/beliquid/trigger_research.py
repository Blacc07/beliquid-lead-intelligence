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
GLOBAL_NEWS_FEEDS = [
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml", "provider": "CoinDesk"},
    {"url": "https://cointelegraph.com/rss", "provider": "Cointelegraph"},
]
MAX_WORKERS = 6
TRIGGER_CACHE_VERSION = 2
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


def _match_feed_payload(record: dict[str, Any], feed_url: str, feed: dict[str, Any], observed_at: str, reused_from_cache: bool = False, source_scope: str = "project_linked", provider: str | None = None) -> dict[str, Any]:
    base = {
        "cache_version": TRIGGER_CACHE_VERSION,
        "project_name": record.get("project_name", ""),
        "chain": record.get("chain", ""),
        "contract_address": record.get("contract_address", ""),
        "feed_url": feed_url,
        "final_feed_url": feed.get("feed_url") or feed_url,
        "provider": provider or feed.get("provider") or "candidate project feed",
        "source_scope": source_scope,
        "observed_at": observed_at,
        "fetch_status": "success",
        "entries_checked": len(feed.get("entries", [])),
        "undated_matches": 0,
        "trigger_candidates": [],
        "reused_from_cache": reused_from_cache,
        "outreach_enabled": False,
    }
    name = str(record.get("project_name") or "").strip().casefold()
    symbol = str(record.get("token_symbol") or "").strip().casefold()
    contract = str(record.get("contract_address") or "").strip().casefold()
    entities = [value for value in (name, symbol, contract) if len(value) >= 4]
    candidates = []
    undated = 0
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
        if not entry.get("published_at"):
            undated += 1
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
            "provider": provider or feed.get("provider") or "candidate project feed",
            "source_scope": source_scope,
            "published_at": entry.get("published_at"),
            "observed_at": observed_at,
            "date_verified": True,
            "note": "Dated feed item matched project metadata and a trigger term; event attribution still requires corroboration.",
        })
    base.update(undated_matches=undated, trigger_candidates=candidates)
    return base


def research_feed(record: dict[str, Any], feed_url: str, observed_at: str, fetcher=fetch_feed) -> dict[str, Any]:
    try:
        feed = fetcher(feed_url)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
        return {
            "cache_version": TRIGGER_CACHE_VERSION,
            "project_name": record.get("project_name", ""),
            "chain": record.get("chain", ""),
            "contract_address": record.get("contract_address", ""),
            "feed_url": feed_url,
            "observed_at": observed_at,
            "fetch_status": "fetch_failed",
            "error_type": type(exc).__name__,
            "entries_checked": 0,
            "trigger_candidates": [],
            "reused_from_cache": False,
            "outreach_enabled": False,
        }
    return _match_feed_payload(record, feed_url, feed, observed_at)


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


def collect_trigger_research(prospect_payload: dict[str, Any], public_research: dict[str, Any], observed_at: str | None = None, fetcher=fetch_feed, previous_payload: dict[str, Any] | None = None, cache_ttl_hours: float = 24, global_feeds: list[dict[str, str]] | None = None) -> dict[str, Any]:
    prospects = prospect_payload.get("records")
    public_records = public_research.get("records")
    if not isinstance(prospects, list) or not isinstance(public_records, list):
        raise ValueError("prospect and public research inputs must contain records lists")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    prior_records = previous_payload.get("records", []) if isinstance(previous_payload, dict) else []
    prior_by_key = {f"{str(item.get('chain') or '').casefold()}:{str(item.get('contract_address') or '').casefold()}": item for item in prior_records if isinstance(item, dict)}
    prior_global = {item.get("feed_url"): item for item in (previous_payload.get("global_feed_results", []) if isinstance(previous_payload, dict) else []) if isinstance(item, dict)}
    prospect_map = {f"{str(r.get('chain') or '').casefold()}:{str(r.get('contract_address') or '').casefold()}": r for r in prospects if isinstance(r, dict)}
    project_jobs = []
    cached_project_results = []
    for public in public_records:
        if not isinstance(public, dict):
            continue
        key = f"{str(public.get('chain') or '').casefold()}:{str(public.get('contract_address') or '').casefold()}"
        prospect = prospect_map.get(key)
        if not prospect:
            continue
        prior = prior_by_key.get(key, {})
        prior_feeds = {item.get("feed_url"): item for item in prior.get("feed_results", []) if isinstance(item, dict) and item.get("source_scope", "project_linked") == "project_linked"}
        for feed in (public.get("feed_candidates") or [])[:MAX_FEEDS_PER_PROSPECT]:
            if not isinstance(feed, dict) or not isinstance(feed.get("url"), str):
                continue
            cached = prior_feeds.get(feed["url"])
            if cached and cached.get("cache_version") == TRIGGER_CACHE_VERSION and cached.get("fetch_status") == "success" and _within_cache_ttl(cached.get("observed_at"), cache_ttl_hours, now):
                item = dict(cached)
                item["reused_from_cache"] = True
                cached_project_results.append(item)
            else:
                project_jobs.append((prospect, feed["url"]))

    configured_global_feeds = GLOBAL_NEWS_FEEDS if global_feeds is None else global_feeds
    global_jobs = []
    cached_global_results = []
    for feed in configured_global_feeds:
        url = feed.get("url")
        if not isinstance(url, str):
            continue
        cached = prior_global.get(url)
        if cached and cached.get("cache_version") == TRIGGER_CACHE_VERSION and cached.get("fetch_status") == "success" and _within_cache_ttl(cached.get("observed_at"), cache_ttl_hours, now):
            item = dict(cached)
            item["reused_from_cache"] = True
            cached_global_results.append(item)
        else:
            global_jobs.append(feed)

    def run_project(job):
        item = research_feed(job[0], job[1], timestamp, fetcher)
        item["reused_from_cache"] = False
        item["source_scope"] = "project_linked"
        return item

    def run_global(feed):
        url = feed["url"]
        try:
            fetched = fetcher(url)
            return {
                "cache_version": TRIGGER_CACHE_VERSION, "provider": feed.get("provider", "global news feed"),
                "feed_url": url, "final_feed_url": fetched.get("feed_url") or url,
                "observed_at": timestamp, "fetch_status": "success",
                "entries_checked": len(fetched.get("entries", [])), "entries": fetched.get("entries", [])[:MAX_ENTRIES_PER_FEED],
                "reused_from_cache": False, "source_scope": "global_news",
            }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
            return {"cache_version": TRIGGER_CACHE_VERSION, "provider": feed.get("provider", "global news feed"),
                    "feed_url": url, "observed_at": timestamp, "fetch_status": "fetch_failed",
                    "error_type": type(exc).__name__, "entries_checked": 0, "entries": [],
                    "reused_from_cache": False, "source_scope": "global_news"}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        project_results = cached_project_results + list(pool.map(run_project, project_jobs))
        global_results = cached_global_results + list(pool.map(run_global, global_jobs))

    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in project_results:
        key = f"{str(result.get('chain') or '').casefold()}:{str(result.get('contract_address') or '').casefold()}"
        grouped.setdefault(key, []).append(result)

    records = []
    total_candidates = 0
    for prospect in prospects:
        if not isinstance(prospect, dict):
            continue
        key = f"{str(prospect.get('chain') or '').casefold()}:{str(prospect.get('contract_address') or '').casefold()}"
        feeds = list(grouped.get(key, []))
        for global_result in global_results:
            if global_result.get("fetch_status") != "success":
                feeds.append({
                    "cache_version": TRIGGER_CACHE_VERSION, "project_name": prospect.get("project_name", ""),
                    "chain": prospect.get("chain", ""), "contract_address": prospect.get("contract_address", ""),
                    "feed_url": global_result.get("feed_url"), "observed_at": global_result.get("observed_at", timestamp),
                    "fetch_status": global_result.get("fetch_status"), "source_scope": "global_news",
                    "provider": global_result.get("provider"), "trigger_candidates": [], "reused_from_cache": global_result.get("reused_from_cache", False),
                })
                continue
            matched = _match_feed_payload(prospect, global_result["feed_url"], global_result, global_result.get("observed_at", timestamp),
                                          bool(global_result.get("reused_from_cache")), "global_news", global_result.get("provider"))
            feeds.append(matched)
        total_candidates += sum(len(item.get("trigger_candidates", [])) for item in feeds)
        records.append({
            "project_name": prospect.get("project_name", ""),
            "chain": prospect.get("chain", ""),
            "contract_address": prospect.get("contract_address", ""),
            "project_feeds_attempted": sum(item.get("source_scope") == "project_linked" and not item.get("reused_from_cache") for item in feeds),
            "global_feeds_processed": sum(item.get("source_scope") == "global_news" for item in feeds),
            "feeds_succeeded": sum(item.get("fetch_status") == "success" for item in feeds),
            "feeds_failed": sum(item.get("fetch_status") == "fetch_failed" for item in feeds),
            "trigger_candidates": [candidate for item in feeds for candidate in item.get("trigger_candidates", [])],
            "feed_results": feeds,
            "buying_trigger_status": "unknown",
            "outreach_enabled": False,
        })
    source_results = project_results + global_results
    return {
        "schema_version": 1,
        "cache_version": TRIGGER_CACHE_VERSION,
        "source": "Linked project RSS/Atom feeds plus CoinDesk and Cointelegraph public RSS feeds",
        "records_exported": len(records),
        "feeds_attempted": len(project_jobs) + len(global_jobs),
        "feeds_processed": len(source_results),
        "feeds_succeeded": sum(item.get("fetch_status") == "success" and not item.get("reused_from_cache") for item in source_results),
        "feeds_failed": sum(item.get("fetch_status") == "fetch_failed" and not item.get("reused_from_cache") for item in source_results),
        "feeds_reused_from_cache": sum(bool(item.get("reused_from_cache")) for item in source_results),
        "cache_ttl_hours": cache_ttl_hours,
        "trigger_candidates": total_candidates,
        "verified_triggers_created": 0,
        "canonical_buying_trigger_reviews_changed": False,
        "qualification_scores_changed": False,
        "outreach_enabled": False,
        "global_feed_results": global_results,
        "records": records,
    }


def write_trigger_research(prospect_path: Path, public_path: Path, output_path: Path, previous_path: Path | None = None, cache_ttl_hours: float = 24) -> dict[str, Any]:
    prospect = json.loads(prospect_path.read_text(encoding="utf-8"))
    public = json.loads(public_path.read_text(encoding="utf-8"))
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path and previous_path.is_file() else None
    result = collect_trigger_research(prospect, public, previous_payload=previous, cache_ttl_hours=cache_ttl_hours)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: result[key] for key in ("records_exported", "feeds_attempted", "feeds_processed", "feeds_succeeded", "feeds_failed", "feeds_reused_from_cache", "trigger_candidates", "outreach_enabled")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--public-research", type=Path, default=Path("artifacts/automated-research.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/trigger-research.json"))
    parser.add_argument("--previous", type=Path, default=Path(".cache/research-state/trigger-research.json"))
    parser.add_argument("--cache-ttl-hours", type=float, default=24)
    args = parser.parse_args()
    try:
        print(json.dumps(write_trigger_research(args.input, args.public_research, args.output, args.previous, args.cache_ttl_hours), indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
