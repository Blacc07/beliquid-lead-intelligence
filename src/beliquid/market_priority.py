"""Explainable market-metric research triage; not a lead score or risk verdict.

Thresholds are pilot heuristics and must be calibrated against reviewed examples.
Metrics describe the selected matching pool, not the project's entire market.
"""
from __future__ import annotations

from typing import Any

# Deliberately explicit pilot thresholds; these do not establish buying intent.
MIN_ACTIVITY_VOLUME_USD = 25_000.0
STRONG_ACTIVITY_VOLUME_USD = 50_000.0
LOW_LIQUIDITY_USD = 25_000.0
IMBALANCE_VOLUME_TO_LIQUIDITY = 2.0


def prioritize_market_research(metrics: dict[str, Any]) -> dict[str, Any]:
    """Return a transparent research queue label from observed metrics only."""
    volume = metrics.get("volume_24h_usd")
    liquidity = metrics.get("liquidity_usd")
    flags: list[str] = []
    reasons: list[str] = []

    valid_volume = isinstance(volume, (int, float)) and not isinstance(volume, bool) and volume >= 0
    valid_liquidity = isinstance(liquidity, (int, float)) and not isinstance(liquidity, bool) and liquidity >= 0
    if not valid_volume:
        volume = None
        flags.append("volume_unknown")
    if not valid_liquidity:
        liquidity = None
        flags.append("liquidity_unknown")

    ratio = None
    if volume is not None and liquidity is not None and liquidity > 0:
        ratio = round(volume / liquidity, 4)

    high_priority = False
    if volume is not None and liquidity == 0 and volume >= MIN_ACTIVITY_VOLUME_USD:
        high_priority = True
        flags.append("reported_zero_liquidity_with_activity")
        reasons.append("Reported liquidity is zero while 24-hour volume meets the pilot activity threshold; verify source/pool data.")
    elif volume is not None and liquidity is not None:
        if liquidity <= LOW_LIQUIDITY_USD and volume >= STRONG_ACTIVITY_VOLUME_USD:
            high_priority = True
            flags.append("activity_with_low_reported_liquidity")
            reasons.append("24-hour volume is at least $50,000 while selected-pool liquidity is at most $25,000.")
        elif ratio is not None and ratio >= IMBALANCE_VOLUME_TO_LIQUIDITY and volume >= MIN_ACTIVITY_VOLUME_USD:
            high_priority = True
            flags.append("volume_liquidity_imbalance_candidate")
            reasons.append("24-hour volume is at least twice selected-pool liquidity and at least $25,000; investigate before interpreting.")
    if volume is not None and volume >= MIN_ACTIVITY_VOLUME_USD:
        flags.append("activity_threshold_met")
        if not reasons:
            reasons.append("24-hour volume meets the $25,000 pilot research threshold; activity alone is not service fit.")
    if liquidity is not None and liquidity <= LOW_LIQUIDITY_USD:
        flags.append("low_reported_liquidity")
        if not reasons:
            reasons.append("Selected-pool reported liquidity is at most $25,000; assess pool coverage and market quality.")
    if volume is None and liquidity is None:
        priority = "insufficient_data"
        reasons.append("Volume and liquidity are unknown; collect reliable metrics before triage.")
    elif high_priority:
        priority = "high"
    elif (volume is not None and volume >= MIN_ACTIVITY_VOLUME_USD) or (
        liquidity is not None and liquidity > LOW_LIQUIDITY_USD
    ):
        priority = "medium"
        if not reasons:
            reasons.append("Some market activity or liquidity is observable, but no pilot imbalance trigger was detected.")
    else:
        priority = "low"
        reasons.append("Observed volume is below the pilot activity threshold and reported liquidity is not elevated.")

    return {
        "priority": priority,
        "signals": list(dict.fromkeys(flags)),
        "reasons": list(dict.fromkeys(reasons)),
        "volume_24h_usd": volume,
        "liquidity_usd": liquidity,
        "volume_to_liquidity_ratio": ratio,
        "thresholds": {
            "minimum_activity_volume_usd": MIN_ACTIVITY_VOLUME_USD,
            "strong_activity_volume_usd": STRONG_ACTIVITY_VOLUME_USD,
            "low_liquidity_usd": LOW_LIQUIDITY_USD,
            "imbalance_volume_to_liquidity": IMBALANCE_VOLUME_TO_LIQUIDITY,
        },
        "qualification_score": None,
        "buying_intent_verified": False,
        "note": "Research prioritization only. Thresholds are unvalidated pilot heuristics; metrics describe one selected pool and do not prove service need, identity, safety, or buying intent.",
    }
