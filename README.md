# BeLiquid Lead Intelligence

Automated discovery, identity research, market-quality analysis, qualification, and human-reviewed business-development routing for BeLiquid Agency's crypto market-making and liquidity services.

## Current status

**Foundation implemented; BeLiquid-specific qualification model is a proposed pilot baseline.** The workflow runs offline unit tests, discovers token profiles, enriches token names/symbols and market metrics from DEX Screener, emits structured summaries, and exports the complete batch as CSV/JSON GitHub Actions artifacts. The market research priority labels are also unvalidated pilot heuristics, not a lead score. The current six-criterion scorecard is a hypothesis to validate, not a BeLiquid-published or sales-validated model. Criteria remain unknown until criterion-specific evidence is reviewed, so scores are withheld. Market metrics are observations, not buying intent. Identity/security concerns must be routed independently of score. The system does not contact prospects.

## Run locally

Requires Python 3.12 or later.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m beliquid.main
PYTHONPATH=src python -m beliquid.sources.dexscreener
PYTHONPATH=src python -m beliquid.sources.enrichment
```

The discovery command makes one live HTTP request. The enrichment command fetches the latest profiles and batches token lookups by chain, with up to 30 addresses per request. Unit tests use mocked responses and do not require network access.

## Run on GitHub Actions

1. Open the **Actions** tab.
2. Select **BeLiquid Pipeline Health Check**.
3. Choose **Run workflow** to execute it manually.
4. Review the unit-test output, discovery/enrichment summary, and runtime health summary.
5. Open the run's **Artifacts** section and download `beliquid-prospect-review-<run number>`. It contains `prospect-review.csv`, `prospect-review.json`, and `pipeline-summary.json`. The CSV includes reviewer status, evidence URL, observed timestamp, and reviewer-note columns for each criterion; those fields start as unknown/blank and do not affect scoring automatically. Buying-trigger observations from `config/buying_trigger_reviews.json` are also exported with their evidence URL, observation timestamp, optional event date, and verified/inferred/unknown status. Trigger labels do not automatically change scores or identity/risk routing. Artifacts are retained for 14 days.

The workflow is scheduled daily at 08:00 UTC. Scheduled jobs can be delayed. Usage limits depend on the repository's plan, runner type, and GitHub's current policies; public visibility does not guarantee unlimited use of every runner type.

## Proposed BeLiquid qualification model

The configurable pilot baseline totals 100 points:

| Criterion | Weight | Evidence focus |
|---|---:|---|
| Service fit and demonstrated need | 25 | Observed spreads, depth, slippage, fragmented liquidity, or explicit liquidity initiative |
| Market activity and commercial potential | 20 | Timestamped activity, liquidity, venue coverage, depth, and consistency—not volume alone |
| Buying trigger and timing | 20 | Dated TGE/launch, listing, new pair, venue expansion, or documented market-quality issue |
| Project credibility and team access | 15 | Cross-verified project/contract identity, operating activity, legitimate public business contact |
| Growth and strategic potential | 10 | Verifiable product development, ecosystem expansion, integrations, and milestones |
| Security and reputational integrity | 10 | Evidence-backed review; unknown does not mean safe |

These weights are a starting hypothesis supplied for this project. They must be validated against manually reviewed examples and eventual sales outcomes before being treated as predictive. Risk flags remain independent of score; unresolved identity, security, or market-integrity concerns should trigger a manual hold regardless of score.

## Workflow stages

1. **Discover:** collect token/project candidates from supported public sources and preserve source timestamps.
2. **Verify identity and risk:** cross-check chain, contract, official domain, and credible project references; hold conflicting identities.
3. **Diagnose market quality:** measure liquidity separately from volume. Add spread, order-book depth, slippage, cross-venue divergence, and time-series analysis only when suitable source data is available.
4. **Review buying triggers:** add human-reviewed, dated event evidence in `config/buying_trigger_reviews.json`. Supported types include exchange listings, new trading pairs, TGE/launch, venue expansion, documented liquidity issues, milestones/campaigns, and token unlocks. Verified/inferred entries require an HTTP(S) source URL, timezone-aware observation timestamp, and summary. This component validates and exports reviewer input; it does not crawl news or treat market metrics as buying intent.
5. **Score and route:** score only reviewed criterion evidence; keep data completeness and risk flags separate; route to research, nurture, BD review, manual hold, or reject.
6. **Prepare outreach drafts:** generate evidence-backed service angles and discovery questions for human review. Sending remains disabled.

## DEX Screener source notes

- Discovery endpoint: `GET https://api.dexscreener.com/token-profiles/latest/v1`.
- The profile feed supplies chain IDs and token addresses but does not guarantee project identity or market metrics.
- The enrichment adapter batches `GET /tokens/v1/{chainId}/{tokenAddresses}` lookups by chain, up to 30 addresses per request.
- Market metrics describe the highest-liquidity matching pool for each token; they are not totals across all pools. `pool_count` records matching pools returned.
- A successful lookup with no matching pools sets `pool_count` to zero but leaves market metrics unknown. Failed requests are reported and must not be interpreted as zero activity.
- Website links supplied by token profiles are unverified candidate metadata. A non-social URL still requires identity verification.
- Review the [DEX Screener API reference](https://docs.dexscreener.com/api/reference) and [API terms](https://docs.dexscreener.com/api/api-terms-and-conditions) before expanding commercial use or distributing data.

## Project layout

- `.github/workflows/health-check.yml` — scheduled/manual GitHub Actions pipeline.
- `src/beliquid/models.py` — validated prospect/evidence records and deduplication keys.
- `src/beliquid/sources/dexscreener.py` — profile discovery and normalization.
- `src/beliquid/sources/enrichment.py` — batched market-data enrichment and export integration.
- `src/beliquid/qualification.py` — config validation and conservative qualification integration.
- `config/qualification_criteria.json` — proposed BeLiquid-specific weights, evidence definitions, trigger labels, and routes.
- `src/beliquid/scoring.py` — evidence-backed score primitives; unknowns and review flags are handled conservatively.
- `src/beliquid/review_export.py` — full-batch CSV/JSON review artifacts.
- `src/beliquid/buying_triggers.py` — validates human-reviewed buying-trigger observations.
- `tests/` — offline tests for models, sources, scoring, qualification, and exports.

## Data-quality and safety rules

- Unknown metric values remain `None`; they are not silently treated as zero.
- Confirmed/not-present criterion findings require evidence URLs and timezone-aware timestamps.
- Discovery and market metrics do not automatically confirm qualification criteria.
- Volume spikes, token promotions, and paid boosts are not treated as quality or buying-intent signals by themselves.
- Risk flags are independent of score. A high score never overrides a manual hold.
- No automated outreach is enabled.
- The repository is public; never commit credentials or secrets.

## Roadmap

1. Verify complete-batch exports and the revised configuration in GitHub Actions.
2. Add contract/project identity verification and independent security/manual-hold routing.
3. Add supported market-quality measurements with provenance and clear limitations.
4. Add externally sourced buying-trigger discovery and source-specific adapters; the current component validates and exports human-reviewed trigger evidence only.
5. Add reviewed criterion assessments and action recommendations.
6. Validate the proposed scoring model against a manually reviewed pilot batch.
7. Later, add persistence and human-approved outreach drafts.
