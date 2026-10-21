"""Offline tests for the DEX Screener adapter; no network calls are made."""

import json
import unittest
from urllib.error import HTTPError

from beliquid.sources.dexscreener import (
    API_URL,
    DexScreenerHTTPError,
    DexScreenerRateLimitError,
    DexScreenerResponseError,
    DexScreenerUnavailableError,
    fetch_latest_profiles,
    normalize_profiles,
)


SAMPLE_PROFILE = {
    "chainId": "base",
    "tokenAddress": "0xAbCd",
    "url": "https://dexscreener.com/base/0xabcd",
    "description": "Example token profile",
    "links": [
        {"type": "twitter", "url": "https://social.example/project"},
        {"type": "website", "label": "Website", "url": "https://project.example"},
    ],
}


class NormalizeProfilesTests(unittest.TestCase):
    def test_normalizes_profile_and_preserves_evidence(self):
        records = normalize_profiles([SAMPLE_PROFILE], observed_at="2026-10-21T13:00:00Z")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.project_name, "0xAbCd")
        self.assertEqual(record.chain, "base")
        self.assertEqual(record.contract_address, "0xAbCd")
        self.assertEqual(record.website_url, "https://project.example")
        self.assertEqual(record.evidence[0].source_name, "DEX Screener")
        self.assertEqual(record.evidence[0].source_url, SAMPLE_PROFILE["url"])
        self.assertEqual(record.evidence[0].observed_at, "2026-10-21T13:00:00Z")
        self.assertEqual(record.metrics, {})

    def test_does_not_mistake_social_link_for_official_website(self):
        profile = {**SAMPLE_PROFILE, "links": [{"type": "twitter", "url": "https://social.example/project"}]}
        self.assertIsNone(normalize_profiles([profile])[0].website_url)

    def test_uses_api_url_when_profile_evidence_url_is_invalid(self):
        profile = {**SAMPLE_PROFILE, "url": "javascript:alert(1)"}
        self.assertEqual(normalize_profiles([profile])[0].evidence[0].source_url, API_URL)

    def test_skips_malformed_items_and_missing_identity(self):
        records = normalize_profiles([None, {"chainId": "base"}, SAMPLE_PROFILE])
        self.assertEqual(len(records), 1)

    def test_deduplicates_same_chain_and_contract(self):
        duplicate = {**SAMPLE_PROFILE, "tokenAddress": "0xabcd", "url": "https://dexscreener.com/base/0xabcd"}
        self.assertEqual(len(normalize_profiles([SAMPLE_PROFILE, duplicate])), 1)

    def test_requires_array_response(self):
        with self.assertRaises(DexScreenerResponseError):
            normalize_profiles({"data": [SAMPLE_PROFILE]})


class FetchLatestProfilesTests(unittest.TestCase):
    def test_fetches_documented_endpoint_and_normalizes_json(self):
        seen = {}

        def transport(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["accept"] = request.get_header("Accept")
            return json.dumps([SAMPLE_PROFILE]).encode("utf-8")

        records = fetch_latest_profiles(timeout=3, transport=transport)
        self.assertEqual(len(records), 1)
        self.assertEqual(seen["url"], API_URL)
        self.assertEqual(seen["timeout"], 3)
        self.assertEqual(seen["accept"], "application/json")

    def test_rejects_non_positive_timeout(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            fetch_latest_profiles(timeout=0, transport=lambda request, timeout: b"[]")

    def test_handles_invalid_json(self):
        with self.assertRaises(DexScreenerResponseError):
            fetch_latest_profiles(transport=lambda request, timeout: b"not json")

    def test_handles_http_429_without_retrying(self):
        def rate_limited(request, timeout):
            raise HTTPError(API_URL, 429, "rate limited", hdrs=None, fp=None)

        with self.assertRaises(DexScreenerRateLimitError):
            fetch_latest_profiles(transport=rate_limited)

    def test_handles_other_http_errors(self):
        def unavailable_http(request, timeout):
            raise HTTPError(API_URL, 503, "service unavailable", hdrs=None, fp=None)

        with self.assertRaises(DexScreenerHTTPError):
            fetch_latest_profiles(transport=unavailable_http)

    def test_handles_network_errors(self):
        def unavailable_network(request, timeout):
            raise TimeoutError("timed out")

        with self.assertRaises(DexScreenerUnavailableError):
            fetch_latest_profiles(transport=unavailable_network)


if __name__ == "__main__":
    unittest.main()
