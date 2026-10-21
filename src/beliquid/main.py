"""Initial health check for the BeLiquid lead intelligence pipeline."""

from __future__ import annotations

import json
import logging
import platform
import sys
import time
from datetime import datetime, timezone
from typing import Any


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("beliquid")


def run_health_check() -> dict[str, Any]:
    """Validate the Python runtime and return a structured run summary."""
    started = time.monotonic()
    checks: dict[str, bool] = {}

    try:
        checks["python_version"] = sys.version_info >= (3, 12)
        checks["utc_clock"] = datetime.now(timezone.utc).utcoffset().total_seconds() == 0

        failed_checks = [name for name, passed in checks.items() if not passed]

        return {
            "application": "beliquid-lead-intelligence",
            "status": "success" if not failed_checks else "failure",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "python_version": platform.python_version(),
            "platform": platform.system(),
            "checks": checks,
            "failed_checks": failed_checks,
            "duration_seconds": round(time.monotonic() - started, 4),
            "records_discovered": 0,
            "leads_qualified": 0,
            "external_sources_called": 0,
            "note": "Bootstrap check only; discovery is not implemented yet.",
        }

    except Exception as exc:
        LOGGER.exception("Health check encountered an unexpected error.")
        return {
            "application": "beliquid-lead-intelligence",
            "status": "failure",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "error_type": type(exc).__name__,
            "duration_seconds": round(time.monotonic() - started, 4),
        }


def main() -> int:
    """Run the health check and return an appropriate process exit code."""
    result = run_health_check()
    LOGGER.info("Run summary: %s", json.dumps(result, sort_keys=True))

    if result.get("status") != "success":
        LOGGER.error("Pipeline health check failed.")
        return 1

    LOGGER.info("Pipeline health check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
