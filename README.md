# BeLiquid Lead Intelligence

Automated discovery, qualification, scoring, and routing of potential crypto/Web3 liquidity-service prospects for BeLiquid Agency.

## Current status

**Phase 1 bootstrap only.** The current workflow validates the Python runtime and emits a structured run summary. It does not yet call external data providers, discover tokens, score prospects, persist records, or contact leads.

## Run locally

Requires Python 3.12 or later.

```bash
PYTHONPATH=src python -m beliquid.main
```

The process prints a JSON summary and exits non-zero if a required health check fails.

## Run on GitHub Actions

1. Open the **Actions** tab.
2. Select **BeLiquid Pipeline Health Check**.
3. Choose **Run workflow** to execute it manually.
4. Review the job logs and the run summary.

The workflow is also scheduled daily at 08:00 UTC. GitHub-hosted scheduled jobs can be delayed and are not guaranteed to start at the exact minute.

## Project layout

- `.github/workflows/health-check.yml` — manual and scheduled bootstrap check.
- `src/beliquid/main.py` — structured health check entry point.
- `src/beliquid/__init__.py` — Python package marker.

## Security and data handling

No API credentials or database secrets are required for the bootstrap check. Add future credentials only through GitHub Actions secrets or the deployment platform's secret manager. Never commit real credentials.

## Roadmap

1. Validate this execution foundation.
2. Add independently tested public data-source adapters.
3. Normalize and deduplicate project/token records.
4. Add evidence-backed buying triggers and configurable lead scoring.
5. Add persistent storage and CSV export.
6. Add contact research and human-approved outreach drafts.
