"""Cross-check candidate project identity against public chain-explorer metadata.

Explorer and homepage evidence are corroboration signals only. This module never writes
canonical verified/mismatch statuses or clears risk.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from beliquid.automated_research import _fetch_with_retries, fetch_page

EXPLORERS = {
    "ethereum": ("https://etherscan.io/token/{address}", "1"),
    "eth": ("https://etherscan.io/token/{address}", "1"),
    "bsc": ("https://bscscan.com/token/{address}", "56"),
    "base": ("https://basescan.org/token/{address}", "8453"),
    "polygon": ("https://polygonscan.com/token/{address}", "137"),
    "arbitrum": ("https://arbiscan.io/token/{address}", "42161"),
    "optimism": ("https://optimistic.etherscan.io/token/{address}", "10"),
    "solana": ("https://solscan.io/token/{address}", "mainnet-beta"),
    "sol": ("https://solscan.io/token/{address}", "mainnet-beta"),
}
ACCOUNT_HOSTS = {"x.com", "twitter.com", "github.com", "discord.com", "discord.gg", "t.me", "telegram.me", "linkedin.com", "youtube.com", "medium.com"}
CONTACT_TERMS = ("contact", "team", "partnership", "business", "about")


def _key(record: dict[str, Any]) -> str:
    return f"{str(record.get('chain') or '').strip().casefold()}:{str(record.get('contract_address') or '').strip().casefold()}"


def _host(url: Any) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.") if isinstance(url, str) else ""


def _contains_token(value: str, token: str) -> bool:
    if not token.strip():
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token.casefold())}(?![a-z0-9])", value.casefold()))


def crosscheck_record(prospect: dict[str, Any], public_record: dict[str, Any] | None,
                      observed_at: str, fetcher: Callable[[str], dict[str, Any]] = fetch_page) -> dict[str, Any]:
    chain = str(prospect.get("chain") or "").strip().casefold()
    address = str(prospect.get("contract_address") or "").strip()
    candidate_url = prospect.get("website_url_candidate")
    if not candidate_url and isinstance(public_record, dict):
        candidate_url = public_record.get("candidate_website_url")
    result: dict[str, Any] = {
        "project_name": prospect.get("project_name", ""), "token_symbol": prospect.get("token_symbol", ""),
        "chain": prospect.get("chain", ""), "contract_address": prospect.get("contract_address", ""),
        "observed_at": observed_at, "candidate_website_url": candidate_url,
        "candidate_website_domain": _host(candidate_url), "chain_explorer_url": None,
        "chain_identifier": None, "fetch_status": "not_attempted",
        "identity_candidate_assessment": {"status": "unresolved", "confidence": 0.0,
            "confidence_is_probability": False, "signals": [], "conflicts": [], "source_urls": [], "observed_at": observed_at},
        "canonical_identity_status_changed": False, "canonical_risk_status_changed": False,
        "qualification_scores_changed": False, "outreach_enabled": False,
    }
    if not address:
        result.update(fetch_status="missing_contract_address", research_note="No contract/mint address; identity remains unknown.")
        return result
    explorer = EXPLORERS.get(chain)
    if not explorer:
        result.update(fetch_status="unsupported_chain", research_note="No configured explorer mapping; chain and identity remain unknown.")
        return result
    template, chain_id = explorer
    explorer_url = template.format(address=address)
    result.update(chain_explorer_url=explorer_url, chain_identifier=chain_id)
    try:
        page = _fetch_with_retries(explorer_url, fetcher)
    except Exception as exc:
        result.update(fetch_status="fetch_failed", research_note=f"Chain-explorer lookup failed ({type(exc).__name__}); identity remains unknown.")
        return result
    title = str(page.get("page_title") or "")
    metadata = " ".join((title, str(page.get("meta_description") or ""), str(page.get("og_site_name") or ""), str(page.get("text_excerpt") or "")))
    symbol = str(prospect.get("token_symbol") or "").strip()
    project_name = str(prospect.get("project_name") or "").strip()
    symbol_match = _contains_token(metadata, symbol)
    name_match = bool(project_name and len(project_name) >= 4 and project_name.casefold() in metadata.casefold())
    contract_on_candidate_site = bool((public_record or {}).get("page", {}).get("contract_address_mentioned"))
    candidate_domain = _host(candidate_url)
    final_explorer_url = page.get("final_url") or explorer_url
    explorer_domains = sorted({_host(urljoin(final_explorer_url, link.get("href", ""))) for link in page.get("links", [])
                               if isinstance(link, dict) and _host(urljoin(final_explorer_url, link.get("href", "")))
                               and _host(urljoin(final_explorer_url, link.get("href", ""))) not in {
                                   "etherscan.io", "bscscan.com", "basescan.org", "polygonscan.com",
                                   "arbiscan.io", "optimistic.etherscan.io", "solscan.io"
                               }})
    candidate_domain_listed = bool(candidate_domain and candidate_domain in explorer_domains)
    public_links = (public_record or {}).get("source_candidates", [])
    account_links = []
    contact_links = []
    for item in public_links if isinstance(public_links, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        host = _host(item["url"])
        if any(host == domain or host.endswith("." + domain) for domain in ACCOUNT_HOSTS):
            account_links.append(item["url"])
        label = str(item.get("label") or "").casefold()
        path_text = (urlparse(item["url"]).path + " " + label).casefold()
        if any(term in path_text for term in CONTACT_TERMS):
            contact_links.append(item["url"])
    signals = [
        {"type": "chain_explorer_page_fetched", "source_url": explorer_url},
        {"type": "candidate_site_mentions_contract", "matched": contract_on_candidate_site},
        {"type": "explorer_token_symbol_match", "matched": symbol_match},
        {"type": "explorer_project_name_match", "matched": name_match},
        {"type": "candidate_domain_listed_by_explorer", "matched": candidate_domain_listed},
        {"type": "project_linked_account_candidates", "count": len(set(account_links))},
        {"type": "public_contact_route_candidates", "count": len(set(contact_links))},
    ]
    conflicts = []
    if contract_on_candidate_site is False and candidate_url:
        conflicts.append({"type": "candidate_site_does_not_mention_contract", "severity": "review",
                          "note": "No exact contract mention was found on the candidate homepage; this is not proof of a mismatch."})
    if candidate_domain and explorer_domains and not candidate_domain_listed:
        conflicts.append({"type": "candidate_domain_differs_from_explorer_links", "severity": "review",
                          "note": "The candidate website domain differs from domains listed on the explorer page; multiple domains or stale metadata may explain this."})
    if symbol and metadata and not symbol_match:
        conflicts.append({"type": "token_symbol_not_matched_by_explorer_metadata", "severity": "review",
                          "note": "Explorer metadata did not contain the supplied symbol; token metadata may be incomplete or inconsistent."})
    strong = contract_on_candidate_site and symbol_match and candidate_domain_listed and bool(account_links) and bool(contact_links)
    status = "corroborated_candidate" if strong else "unresolved"
    confidence = round(sum([0.2 if contract_on_candidate_site else 0,
                            0.2 if symbol_match else 0,
                            0.2 if name_match else 0,
                            0.2 if candidate_domain_listed else 0,
                            0.1 if account_links else 0,
                            0.1 if contact_links else 0]), 2)
    result.update(fetch_status="success", explorer_page={"final_url": page.get("final_url") or explorer_url,
        "page_title": title[:500], "metadata_excerpt": metadata[:2000], "linked_domains": explorer_domains},
        "identity_candidate_assessment":{"status": status, "confidence": confidence, "confidence_is_probability": False,
            "signals": signals, "conflicts": conflicts, "source_urls": [url for url in (candidate_url, page.get("final_url") or explorer_url, *account_links, *contact_links) if url],
            "observed_at": observed_at, "note": "Even a corroborated candidate is not canonical identity verification; only source evidence is recorded."},
        "account_link_candidates": sorted(set(account_links)), "contact_route_candidates": sorted(set(contact_links)),
        "research_note": "Explorer and candidate-site comparisons are corroboration signals only; canonical identity remains unchanged.")
    return result


def collect_identity_crosschecks(prospect_payload: dict[str, Any], public_payload: dict[str, Any] | None = None,
                                 observed_at: str | None = None, fetcher: Callable[[str], dict[str, Any]] = fetch_page) -> dict[str, Any]:
    prospects = prospect_payload.get("records")
    public_records = public_payload.get("records", []) if isinstance(public_payload, dict) else []
    if not isinstance(prospects, list) or any(not isinstance(item, dict) for item in prospects):
        raise ValueError("prospect payload must contain a records list of objects")
    if not isinstance(public_records, list) or any(not isinstance(item, dict) for item in public_records):
        raise ValueError("public research payload must contain a records list of objects")
    public_map = {_key(item): item for item in public_records}
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(crosscheck_record, prospect, public_map.get(_key(prospect)), timestamp, fetcher) for prospect in prospects]
        results = [future.result() for future in futures]
    counts: dict[str, int] = {}
    for item in results:
        status = item["identity_candidate_assessment"]["status"]
        counts[status] = counts.get(status, 0) + 1
    return {"schema_version": 1, "generated_at": timestamp, "source": "public chain explorers plus candidate-site/account cross-checks",
        "records_exported": len(results), "status_counts": counts, "records_with_fetch_failures": sum(item["fetch_status"] == "fetch_failed" for item in results),
        "records_unsupported_chain": sum(item["fetch_status"] == "unsupported_chain" for item in results),
        "canonical_identity_status_changed": False, "canonical_risk_status_changed": False,
        "qualification_scores_changed": False, "outreach_enabled": False, "records": results,
        "note": "The strongest result is corroborated_candidate, never verified. Conflicts and missing metadata remain unresolved and do not auto-clear risk."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--public-research", type=Path, default=Path("artifacts/automated-research.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/identity-crosscheck.json"))
    args = parser.parse_args()
    try:
        prospect = json.loads(args.input.read_text(encoding="utf-8"))
        public = json.loads(args.public_research.read_text(encoding="utf-8")) if args.public_research.is_file() else None
        result = collect_identity_crosschecks(prospect, public)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("records_exported", "status_counts", "records_with_fetch_failures", "records_unsupported_chain", "outreach_enabled")}, indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
