"""Offline tests for batched DEX Screener token enrichment."""

import json
import unittest
from urllib.error import HTTPError

from beliquid.models import Evidence, ProspectRecord
from beliquid.sources.enrichment import (
    TOKENS_URL,
    enrich_records,
    fetch_token_pairs,
)
from beliquid.sources.dexscreener import DexScreenerRateLimitError


def prospect(address="0xToken", chain="base"):
    return ProspectRecord(
        project_name=address,
        chain=chain,
        contract_address=address,
        evidence=(Evidence("DEX Screener", "https://dexscreener.com/base/token", "2026-10-21T12:00:00Z"),),
    )


def pair(address="0xToken", name="Example Token", symbol="EXT", liquidity=1000, price="0.25"):
    return {
        "chainId": "base",
        "dexId": "uniswap",
        "url": "https://dexscreener.com/base/example-pool",
        "pairAddress": "0xPool",
        "baseToken": {"address": address, "name": name, "symbol": symbol},
        "quoteToken": {"address": "0xUSD", "name": "USD Coin", "symbol": "USDC"},
        "priceUsd": price,
        "liquidity": {"usd": liquidity},
        "volume": {"h24": 12500},
        "txns": {"h24": {"buys": 12, "sells": 8}},
        "marketCap": 500000,
        "fdv": 750000,
    }


class FetchTokenPairsTests(unittest.TestCase):
    def test_uses_documented_batched_endpoint(self):
        seen = {}

        def transport(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return b"[]"

        pairs, url = fetch_token_pairs("base", ["0xOne", "0xTwo"], timeout=4, transport=transport)
        self.assertEqual(pairs, [])
        self.assertEqual(url, f"{TOKENS_URL}/base/0xOne,0xTwo")
        self.assertEqual(seen["url"], url)
        self.assertEqual(seen["timeout"], 4)

    def test_rejects_more_than_30_addresses(self):
        with self.assertRaisesRegex(ValueError, "at most 30"):
            fetch_token_pairs("base", [f"0x{i}" for i in range(31)], transport=lambda request, timeout: b"[]")

    def test_handles_rate_limit_without_retrying(self):
        def rate_limited(request, timeout):
            raise HTTPError(request.full_url, 429, "rate limited", hdrs=None, fp=None)

        with self.assertRaises(DexScreenerRateLimitError):
            fetch_token_pairs("base", ["0xOne"], transport=rate_limited)

    def test_rejects_non_array_response(self):
        with self.assertRaisesRegex(Exception, "array of pair objects"):
            fetch_token_pairs("base", ["0xOne"], transport=lambda request, timeout: b'{"pairs": []}')


class EnrichRecordsTests(unittest.TestCase):
    def test_enriches_name_symbol_and_market_metrics_from_best_liquidity_pool(self):
        record = prospect()
        payload = [pair(liquidity=100), pair(name="Example Token", symbol="EXT", liquidity=900)]
        seen = []

        def transport(request, timeout):
            seen.append(request.full_url)
            return json.dumps(payload).encode()

        records, summary = enrich_records([record], transport=transport, observed_at="2026-10-21T13:00:00Z")
        result = records[0]
        self.assertEqual(len(seen), 1)
        self.assertEqual(result.project_name, "Example Token")
        self.assertEqual(result.token_symbol, "EXT")
        self.assertEqual(result.metrics["liquidity_usd"], 900)
        self.assertEqual(result.metrics["price_usd"], 0.25)
        self.assertEqual(result.metrics["volume_24h_usd"], 12500)
        self.assertEqual(result.metrics["market_cap_usd"], 500000)
        self.assertEqual(result.metrics["pool_count"], 2)
        self.assertEqual(result.evidence[-1].evidence_type, "token_market_enrichment")
        self.assertIn("not totals across pools", result.evidence[-1].notes)
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["records_with_market_data"], 1)

    def test_no_matching_pools_keeps_metrics_unknown_and_records_zero_pool_count(self):
        records, summary = enrich_records(
            [prospect()],
            transport=lambda request, timeout: b"[]",
            observed_at="2026-10-21T13:00:00Z",
        )
        result = records[0]
        self.assertEqual(result.project_name, "0xToken")
        self.assertIsNone(result.metrics["price_usd"])
        self.assertIsNone(result.metrics["liquidity_usd"])
        self.assertEqual(result.metrics["pool_count"], 0)
        self.assertEqual(summary["records_with_market_data"], 0)

    def test_ignores_pairs_that_do_not_match_the_requested_contract(self):
        unrelated = pair(address="0xOther", name="Unrelated")
        records, _ = enrich_records([prospect()], transport=lambda request, timeout: json.dumps([unrelated]).encode())
        self.assertEqual(records[0].project_name, "0xToken")
        self.assertIsNone(records[0].metrics["price_usd"])

    def test_failed_batch_preserves_record_and_reports_partial_failure(self):
        def unavailable(request, timeout):
            raise TimeoutError("timed out")

        records, summary = enrich_records([prospect()], transport=unavailable)
        self.assertEqual(records[0].project_name, "0xToken")
        self.assertEqual(summary["status"], "failure")
        self.assertEqual(len(summary["batch_failures"]), 1)
        self.assertEqual(records[0].metrics, {})


if __name__ == "__main__":
    unittest.main()
