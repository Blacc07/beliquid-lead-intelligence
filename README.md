# BeLiquid Lead Intelligence

Automated discovery, qualification, scoring, and routing of potential crypto/Web3 liquidity-service prospects for BeLiquid Agency.

## Current status

**Phase 1 foundation plus first discovery adapter.** The workflow runs standard-library unit tests, calls the DEX Screener latest token profiles endpoint, and emits a structured run summary. It does not yet enrich token addresses into project names, qualify leads, persist records, or contact leads.

## Run locally

Requires Python 3.12 or later.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m beliquid.main
PYTHONPATH=src python -m beliquid.sources.dexscreener
```

The DEX Screener command makes one live HTTP request. Unit tests use mocked responses and do not require network access.

## Run on GitHub Actions

1. Open the **Actions** tab.
2. Select **BeLiquid Pipeline Health Check**.
3. Choose **Run workflow** to execute it manually.
4. Review the unit-test output, DEX Screener discovery summary, and run summary.

The workflow is also scheduled daily at 08:00 UTC. GitHub-hosted scheduled jobs can be delayed and are not guaranteed to start at the exact minute. Usage limits depend on the repository's plan, runner type, and GitHub's current policies; public visibility alone does not guarantee unlimited use of every runner type.

## DEX Screener source notes

- Endpoint: `GET https://api.dexscreener.com/token-profiles/latest/v1`
- The official API reference lists a rate limit of 60 requests per minute for this endpoint. This workflow makes one request per run and does not automatically retry rate-limit responses.
- This feed returns token profile metadata, including chain ID and token address; it does not guarantee a token name or full market metrics. Until a later enrichment step resolves names, the token address is used as the explicit placeholder name.
- A profile listing is only a discovery signal. It is not proof of project quality, liquidity need, or buying intent. Promotion/boost signals must never be treated as quality scores.
- Website links are unverified metadata supplied by token profiles. The adapter rejects common social-platform domains even when labelled as a website, but a non-social URL is still only a candidate and must be verified before outreach.
- Review the [DEX Screener API reference](https://docs.dexscreener.com/api/reference) and [API terms](https://docs.dexscreener.com/api/api-terms-and-conditions) before expanding commercial use or distributing data. Do not resell or expose the API service/data as a third-party API.

## Project layout

- `.github/workflows/health-check.yml` — manual and scheduled check; runs tests and a live source smoke test.
- `src/beliquid/main.py` — runtime health-check entry point; its summary is separate from discovery counts.
- `src/beliquid/models.py` — validated prospect and evidence records with stable deduplication keys.
- `src/beliquid/sources/dexscreener.py` — public API client, response validation, normalization, deduplication, and CLI summary.
- `tests/test_models.py` — tests for record validation, unknown metrics, and deduplication boundaries.
- `tests/test_dexscreener.py` — offline tests for normalization, malformed payloads, network failures, and rate limits.

## Data-quality rules

- Unknown metric values remain `None`; they are not silently treated as zero.
- Evidence URLs must use HTTP or HTTPS and observation timestamps must include a timezone.
- EVM contract addresses are normalized case-insensitively; case is preserved for non-EVM chains.
- When a contract address is unavailable, the fallback deduplication key includes chain, normalized project name, and website host.
- Negative, boolean, NaN, and infinite metric values are rejected.
- Discovery evidence is retained; a listing or paid promotion is not treated as a verified commercial trigger.

## Security and data handling

No API credentials or database secrets are required for the current adapter. Add future credentials only through GitHub Actions secrets or the deployment platform's secret manager. Never commit real credentials. This repository is public, so treat all committed content as publicly visible.

## Roadmap

1. Validate the execution foundation and prospect data model.
2. Add and test public data-source adapters.
3. Enrich token addresses with token names, websites, market metrics, and provenance.
4. Normalize and deduplicate discovered project/token records.
5. Add evidence-backed buying triggers and configurable lead scoring.
6. Add persistent storage and CSV export.
7. Add contact research and human-approved outreach drafts.
