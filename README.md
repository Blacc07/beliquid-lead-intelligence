# BeLiquid Lead Intelligence

Automated discovery, qualification, scoring, and routing of potential crypto/Web3 liquidity-service prospects for BeLiquid Agency.

## Current status

**Phase 1 foundation plus discovery, market enrichment, and a standalone scoring engine.** The workflow runs standard-library unit tests, discovers token profiles, looks up token names/symbols and market data from DEX Screener, and emits a structured summary. The scoring engine and approved starting configuration for liquidity-service qualification are implemented and tested. The live discovery/enrichment run emits conservative qualification reports and now exports the full batch as JSON and CSV GitHub Actions artifacts for manual review. All six criteria remain unknown until criterion-specific evidence is reviewed; therefore scores are withheld. This is not yet a general BeLiquid sales-fit score. Artifacts are retained for 14 days, are not a permanent database, and the system does not contact leads.

## Run locally

Requires Python 3.12 or later.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m beliquid.main
PYTHONPATH=src python -m beliquid.sources.dexscreener
PYTHONPATH=src python -m beliquid.sources.enrichment
```

The discovery command makes one live HTTP request. The enrichment command fetches the latest profiles and then batches token lookups by chain, with up to 30 addresses per request. Unit tests use mocked responses and do not require network access.

## Run on GitHub Actions

1. Open the **Actions** tab.
2. Select **BeLiquid Pipeline Health Check**.
3. Choose **Run workflow** to execute it manually.
4. Review the unit-test output, discovery/enrichment summary, and runtime health summary.\n5. Open the run's **Artifacts** section and download `beliquid-prospect-review-<run number>`. It contains `prospect-review.csv` (spreadsheet-friendly), `prospect-review.json` (complete records and evidence), and `pipeline-summary.json`. The CSV includes editable reviewer status, evidence URL, observed timestamp, and reviewer-note columns for each of the six criteria; those columns start as `unknown`/blank and do not affect scoring automatically. Artifacts are retained for 14 days.

The workflow is also scheduled daily at 08:00 UTC. GitHub-hosted scheduled jobs can be delayed and are not guaranteed to start at the exact minute. Usage limits depend on the repository's plan, runner type, and GitHub's current policies; public visibility alone does not guarantee unlimited use of every runner type.

## DEX Screener source notes

- Endpoint: `GET https://api.dexscreener.com/token-profiles/latest/v1`
- The official API reference lists a rate limit of 60 requests per minute for this endpoint. This workflow makes one request per run and does not automatically retry rate-limit responses.
- The profile feed returns chain IDs and token addresses but does not guarantee token names or market metrics. The enrichment adapter uses the documented `GET /tokens/v1/{chainId}/{tokenAddresses}` endpoint, batching up to 30 addresses per chain request to retrieve matching pools, names, symbols, price, liquidity, 24-hour volume, market cap, FDV, and transaction counts where available.
- Market metrics describe the highest-liquidity matching pool for each token; they are not totals across all pools. `pool_count` records how many matching pools were returned. A successful lookup with no matching pools sets `pool_count` to zero but leaves market metrics unknown. A failed request leaves existing records unchanged and is reported in `batch_failures`.
- Market metrics are volatile observations, not lead-quality scores or evidence of buying intent. Missing values remain unknown; the system does not substitute zero for unavailable price, liquidity, volume, market cap, or FDV.
- A profile listing is only a discovery signal. It is not proof of project quality, liquidity need, or buying intent. Promotion/boost signals must never be treated as quality scores.
- Website links are unverified metadata supplied by token profiles. The adapter rejects common social-platform domains even when labelled as a website, but a non-social URL is still only a candidate and must be verified before outreach.
- Review the [DEX Screener API reference](https://docs.dexscreener.com/api/reference) and [API terms](https://docs.dexscreener.com/api/api-terms-and-conditions) before expanding commercial use or distributing data. Do not resell or expose the API service/data as a third-party API.

## Project layout

- `.github/workflows/health-check.yml` — manual and scheduled check; runs tests and a live source smoke test.
- `src/beliquid/main.py` — runtime health-check entry point; its summary is separate from discovery counts.
- `src/beliquid/models.py` — validated prospect and evidence records with stable deduplication keys.
- `src/beliquid/sources/dexscreener.py` — profile API client, response validation, normalization, deduplication, and CLI summary.
- `src/beliquid/sources/enrichment.py` — batched token-pair lookup, token name/symbol enrichment, market metrics, evidence provenance, partial-failure reporting, and review-export integration.\n- `src/beliquid/review_export.py` — full-batch CSV/JSON review exports with criterion statuses, evidence provenance, and non-judgmental research queues.\n- `src/beliquid/scoring.py` — configurable evidence-backed scoring primitives; unknown criteria are excluded from assessed weight, scores are withheld below an evidence-coverage threshold, and review flags remain independent of score.
- `src/beliquid/qualification.py` — strict criteria-config validation and conservative scoring integration; market metrics never auto-confirm qualification criteria.
- `tests/test_scoring.py` — offline tests for score coverage, evidence requirements, unknown values, duplicate criteria, and review flags.
- `tests/test_models.py` — tests for record validation, unknown metrics, and deduplication boundaries.
- `tests/test_dexscreener.py` — offline tests for normalization, malformed payloads, network failures, and rate limits.
- `tests/test_enrichment.py` — offline tests for batched lookup, market-data selection, unknown metrics, and failed requests.\n- `tests/test_review_export.py` — offline tests for complete-batch export, unknown criteria, and withheld scores.

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
3. Enrich token addresses with token names, symbols, market metrics, and provenance.
4. Normalize and deduplicate discovered project/token records.
5. Add evidence-backed buying triggers and configurable lead scoring.
6. Add persistent storage and CSV export.
7. Add contact research and human-approved outreach drafts.
