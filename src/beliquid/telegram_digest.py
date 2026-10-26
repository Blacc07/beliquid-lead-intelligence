"""Send a private Telegram digest of generated research candidates."""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _priority(record: dict[str, Any]) -> str:
    value = record.get("market_research_priority")
    return str(value.get("priority", "unknown")) if isinstance(value, dict) else "unknown"


def _route(record: dict[str, Any]) -> str:
    return str(record.get("action_route") or "research")


def build_digest(payload: dict[str, Any], run_url: str, limit: int = 10) -> str:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("prospect review JSON must contain a records list")

    # Rank only for triage display. This is not a qualification score.
    ordered = sorted(
        (item for item in records if isinstance(item, dict)),
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(_priority(item).lower(), 3),
            str(item.get("project_name") or "").casefold(),
        ),
    )
    summary = payload.get("qualification_summary") or {}
    scores_issued = summary.get("scores_issued", 0)
    lines = [
        "🔎 <b>BeLiquid lead research digest</b>",
        f"Candidates generated: <b>{len(ordered)}</b>",
        f"Qualification scores issued: <b>{html.escape(str(scores_issued))}</b>",
        "",
        "<i>Research candidates, not verified leads. Identity and risk may be unresolved; missing reports do not mean safe. No prospect outreach is sent.</i>",
        "",
    ]
    if not ordered:
        lines.append("No candidates were generated in this run.")
    for index, record in enumerate(ordered[:limit], 1):
        name = html.escape(str(record.get("project_name") or "Unnamed project"))
        symbol = html.escape(str(record.get("token_symbol") or "—"))
        chain = html.escape(str(record.get("chain") or "unknown"))
        address = str(record.get("contract_address") or "")
        website = str(record.get("website_url_candidate") or "")
        qualification = record.get("qualification") if isinstance(record.get("qualification"), dict) else {}
        score = qualification.get("score_percent")
        score_text = f"{score}%" if score is not None else "withheld"
        priority = html.escape(_priority(record))
        route = html.escape(_route(record))
        lines.append(f"<b>{index}. {name} ({symbol})</b>")
        lines.append(f"Chain: {chain} · Research priority: {priority} · Route: {route}")
        lines.append(f"Qualification: {html.escape(score_text)}")
        if address:
            lines.append(f"Contract: <code>{html.escape(address)}</code>")
        if website:
            safe_website = html.escape(website, quote=True)
            if website.startswith(("https://", "http://")):
                lines.append(f'Candidate site: <a href="{safe_website}">{safe_website}</a> (unverified)')
            else:
                lines.append(f"Candidate site: {safe_website} (unverified)")
        lines.append("")
    if len(ordered) > limit:
        lines.append(f"Showing {min(limit, len(ordered))} of {len(ordered)} candidates.")
    if run_url:
        safe_run_url = html.escape(run_url, quote=True)
        lines.extend(["", f'<a href="{safe_run_url}">Open workflow run and artifacts</a>'])
    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Telegram delivery failed: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API rejected message: {result.get('description', 'unknown error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/prospect-review.json"))
    parser.add_argument("--run-url", default=os.environ.get("GITHUB_RUN_URL", ""))
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("TELEGRAM_DELIVERY_SKIPPED: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID secret is not configured.")
        return 2
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("prospect review JSON must be an object")
        message = build_digest(payload, args.run_url, max(1, min(args.limit, 15)))
        # Telegram's message limit is 4096 characters. Keep each message bounded.
        if len(message) > 3900:
            message = message[:3850] + "\n\nDigest shortened; open the workflow run for the complete export."
        send_message(token, chat_id, message)
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"TELEGRAM_DELIVERY_FAILED: {exc}", file=sys.stderr)
        return 1
    print("TELEGRAM_DELIVERY_SENT: lead research digest accepted by Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
