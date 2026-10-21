# BeLiquid Lead Intelligence

Automated discovery, qualification, scoring, and routing of potential crypto/Web3 liquidity-service prospects for BeLiquid Agency.

## Current status

**Phase 1 foundation.** The workflow validates the Python runtime, runs standard-library unit tests, and emits a structured run summary. Prospect/evidence data models are in place, but the application does not yet call external data providers, discover tokens, score prospects, persist records, or contact leads.

## Run locally

Requires Python 3.12 or later.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m beliquid.main
```

The health-check process prints a JSON summary and exits non-zero if a required check fails.

## Run on GitHub Actions

1. Open the **Actions** tab.
2. Select **BeLiquid Pipeline Health Check**.
3. Choose **Run workflow** to execute it manually.
4. Review the unit-test output and run summary.

The workflow is also scheduled daily at 08:00 UTC. GitHub-hosted scheduled jobs can be delayed and are not guaranteed to start at the exact minute. Usage limits depend on the repository's plan, runner type, and GitHub's current policies; public visibility alone does not guarantee unlimited use of every runner type.

## Project layout

- `.github/workflows/health-check.yml` — manual and scheduled check; runs unit tests first.
- `src/beliquid/main.py` — structured health-check entry point.
- `src/beliquid/models.py` — validated prospect and evidence records with stable deduplication keys.
- `tests/test_models.py` — tests for validation, unknown metrics, and deduplication boundaries.
- `src/beliquid/__init__.py` — Python package marker.

## Data-quality rules

- Unknown metric values remain `None`; they are not silently treated as zero.
- Evidence URLs must use HTTP or HTTPS and observation timestamps must include a timezone.
- EVM contract addresses are normalized case-insensitively; case is preserved for non-EVM chains.
- When a contract address is unavailable, the fallback deduplication key includes chain, normalized project name, and website host.
- Negative, boolean, NaN, and infinite metric values are rejected.

## Security and data handling

No API credentials or database secrets are required for the current foundation. Add future credentials only through GitHub Actions secrets or the deployment platform's secret manager. Never commit real credentials. This repository is public, so treat all committed content as publicly visible.

## Roadmap

1. Validate the execution foundation and prospect data model.
2. Add independently tested public data-source adapters.
3. Normalize and deduplicate discovered project/token records.
4. Add evidence-backed buying triggers and configurable lead scoring.
5. Add persistent storage and CSV export.
6. Add contact research and human-approved outreach drafts.
