# BeLiquid Lead Intelligence

Automated discovery, market-data enrichment, public-page and linked-feed research, contract-security observations, source-backed task progression, and conservative qualification routing for BeLiquid Agency's crypto market-making and liquidity services.

## Current status

**Foundation implemented; BeLiquid-specific qualification model is a proposed pilot baseline.** The workflow runs offline unit tests, discovers token profiles, enriches token names/symbols and market metrics from DEX Screener, emits structured summaries, and exports the complete batch as CSV/JSON GitHub Actions artifacts. The market research priority labels are also unvalidated pilot heuristics, not a lead score. The current six-criterion scorecard is a hypothesis to validate, not a BeLiquid-published or sales-validated model. Criteria remain unknown until criterion-specific evidence is reviewed, so scores are withheld. Market metrics are observations, not buying intent. Identity/security concerns must be routed independently of score. The system does not contact prospects.

## Automated public-page research

The workflow fetches candidate project homepages from the existing DEX Screener profile metadata and writes `automated-research.json`. It captures page metadata, outbound source candidates, and keyword-based buying-trigger/criterion evidence candidates. These are research leads only: they do not automatically verify identity, clear risk, confirm buying intent, or change the six-criterion score. The output is covered by the audit manifest. Pages are fetched with bounded size/time and public-HTTP URL checks; failures remain explicit and statuses stay unknown. This is the first evidence-collection adapter, not yet a complete autonomous evidence system for official identity, independent risk intelligence, buying triggers, or all six criteria.

## Automated research source coverage

The workflow also runs GoPlus contract-security checks for configured EVM chains and RugCheck reports for Solana, discovers RSS/Atom feeds linked by candidate project pages, records dated buying-trigger candidates, and generates a run-local task ledger from source calls that actually completed. High-severity contract flags route the research queue to an automated hold. Clean or missing security reports never establish global safety; trigger candidates remain unverified, canonical identity/risk and trigger reviews are not silently rewritten, scores still use the existing six criteria and 60% evidence-coverage threshold, and outreach remains disabled. See [Automated Research Source Coverage](docs/AUTOMATED_RESEARCH_SOURCES.md) for rate bounds, failure semantics, credentials, and limitations.

## Review procedure

Use the [Evidence-Backed Reviewer Guide](docs/REVIEWER_GUIDE.md) for the exact six-criterion definitions, evidence/status rules, repeatable review-file examples, identity/risk holds, 60% coverage safeguards, and CSV/JSON reconciliation checklist. Review inputs are human-maintained; do not invent evidence or enable automated outreach.

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
5. Open the run's **Artifacts** section and download `beliquid-prospect-review-<run number>`. It contains `prospect-review.csv`, `prospect-review.json`, `pipeline-summary.json`, `automated-research.json`, `security-research.json`, `trigger-research.json`, `research-task-ledger.json`, `research-queue.csv`, `research-queue.json`, pilot-validation reports, and the SHA-256 audit manifest. The CSV includes reviewer status, evidence URL, observed timestamp, and reviewer-note columns for each criterion; those fields start as unknown/blank and do not affect scoring automatically. Buying-trigger observations from `config/buying_trigger_reviews.json` are also exported with their evidence URL, observation timestamp, optional event date, and verified/inferred/unknown status. Criterion assessments from `config/criterion_reviews.json` can be recorded as confirmed/not_present/unknown with matching evidence URLs and timezone-aware timestamps. Only criterion assessments count toward qualification coverage; trigger records do not automatically confirm criteria. Artifacts are retained for 14 days.

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
4. **Research buying triggers:** collect candidate events from RSS/Atom feeds explicitly linked by candidate project pages. The adapter matches project metadata against dated feed entries for listings, launches, partnerships/fundraising, venue expansion, liquidity issues, milestones/campaigns, and unlocks. These remain candidate-only until corroborated; canonical trigger reviews remain separate and market metrics are not buying intent.
5. **Review criteria, score, and route:** enter criterion-specific assessments in `config/criterion_reviews.json`. Confirmed/not_present findings require evidence URLs and timezone-aware timestamps. Scores remain withheld until the configured 60% evidence-coverage threshold is reached. Buying-trigger evidence does not automatically confirm a criterion; keep data completeness and identity/risk flags separate.
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
- `src/beliquid/buying_triggers.py` — validates canonical buying-trigger observations.
- `src/beliquid/automated_research.py` — bounded candidate homepage collection and feed discovery.
- `src/beliquid/security_research.py` — GoPlus EVM and RugCheck Solana contract-risk observations with retry handling.
- `src/beliquid/trigger_research.py` — dated RSS/Atom trigger candidates.
- `src/beliquid/task_ledger.py` — source-backed automated task completion ledger.
- `src/beliquid/criterion_reviews.py` — validates reviewer assessments against configured criteria.
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
4. Expand authoritative buying-trigger coverage beyond feeds linked by candidate project pages and corroborate dated event candidates.
5. Add reviewed criterion assessments and action recommendations.
6. Validate the proposed scoring model against a manually reviewed pilot batch.
7. Later, add persistence and human-approved outreach drafts.
