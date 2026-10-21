# Automated research source coverage

## Current adapters

| Adapter | What it collects | Credentials | Bounds and failure handling | What it does not prove |
|---|---|---|---|---|
| DEX Screener discovery/enrichment | Candidate token profiles, chain/contract metadata, pool and market observations | No key configured by this repository | HTTP errors are surfaced by the existing source module; provider limits may change and must be checked against current DEX Screener documentation | Official identity, buying intent, safety, or qualification |
| Candidate project homepage collector | Bounded HTML metadata, page text excerpt, outbound link candidates, keyword-trigger candidates | No key | Public HTTP(S) URLs only; 8-second timeout; 1 MB body limit; at most 40 links and 20,000 characters of text; fetch failures are explicit and leave statuses unknown | That the candidate homepage is official, that keyword matches are verified events, or that a criterion is satisfied |
| GoPlus Token Security API | Contract-level security flags for configured EVM chain IDs | No API key is configured; public endpoint is used | 8-second timeout; response capped at 1 MB; up to 3 attempts for transient network and HTTP 408/425/429/5xx failures; unsupported chains, missing reports, provider errors, and request failures are distinct outcomes | Global risk clearance, project reputation, source completeness, or identity verification |

## GoPlus coverage

The adapter currently maps Ethereum, BNB Smart Chain, Polygon, Arbitrum, Optimism, Base, Avalanche C-Chain, Fantom, Cronos, Gnosis, Linea, Scroll, and Mantle names to GoPlus chain IDs. Chain aliases are explicit in `src/beliquid/security_research.py`; unrecognized chains are not guessed. Confirm current API support and terms before relying on a newly added chain.

Configured high-severity flags include reported honeypot behavior, inability for some holders to sell, hidden owner capability, self-destruct capability, external-call capability, and owner-controlled balance changes. Additional capabilities such as minting, proxy behavior, blacklist, transfer pause, cooldown, and inability to buy are recorded as review-level observations, not automatically labeled malicious.

A high-severity provider finding creates an automated hold in the research queue. The canonical identity/risk review file and qualification score are not silently rewritten. A report with no configured high-severity flags is labeled `no_high_risk_flag_detected_by_provider`, not `clear`; no report is `unknown`, never safe. A provider flag is a source-backed concern that warrants conservative routing, not conclusive proof of malicious intent.

## Pipeline and task behavior

- `automated-research.json` and `security-research.json` are generated independently from the canonical prospect review export.
- The research queue consumes the security output and routes a reported high-severity finding to an automated hold before commercial research.
- The queue does not convert source results into canonical identity verification or a clean risk review.
- Qualification still uses the existing six criteria and configured 60% evidence-coverage threshold. Candidate keywords and security flags do not automatically confirm criteria or generate a score.
- Task completion is not qualification or clearance. Outreach remains disabled.
- The audit manifest records SHA-256 hashes of both research outputs. Hashes establish artifact integrity, not the truth of a source statement.

## Remaining limitations

This is an initial independent contract-risk integration, not a complete security or reputation engine. There is not yet broad chain coverage, multiple independent security vendors, automated reputational/news-source corroboration, a canonical identity cross-match against official contract announcements, structured feed ingestion for dated buying triggers, or automated criterion-level evidence assessment across all six criteria. Public-page keyword matches remain candidates only. Criterion-level evidence assessment across all six criteria remains incomplete. No failed call should be represented as a completed task.

Provider rate limits and terms can change. The adapter uses bounded retries for transient failures but does not assume a fixed request quota. If GoPlus returns rate limiting or provider errors, the output preserves the failure state and does not mark the prospect clear. No credentials are currently required by this adapter; any future keyed providers should use GitHub Actions secrets and must never write credentials into artifacts or logs.
