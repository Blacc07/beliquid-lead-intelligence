"""Standard-library tests for prospect record validation."""

import math
import unittest

from beliquid.models import Evidence, ProspectRecord


class EvidenceTests(unittest.TestCase):
    def test_requires_timezone_in_observation_timestamp(self):
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            Evidence("Example", "https://example.org/source", "2026-10-21T12:00:00")

    def test_rejects_non_http_source_url(self):
        with self.assertRaisesRegex(ValueError, "http"):
            Evidence("Example", "javascript:alert(1)", "2026-10-21T12:00:00Z")

    def test_rejects_blank_source_url(self):
        with self.assertRaisesRegex(ValueError, "http"):
            Evidence("Example", " ", "2026-10-21T12:00:00Z")

    def test_accepts_utc_z_timestamp(self):
        evidence = Evidence("Example", "https://example.org/source", "2026-10-21T12:00:00Z")
        self.assertEqual(evidence.source_name, "Example")


class ProspectRecordTests(unittest.TestCase):
    def test_unknown_metrics_remain_none(self):
        prospect = ProspectRecord("Sample Protocol", "Base", metrics={"tvl_usd": None})
        self.assertIsNone(prospect.metrics["tvl_usd"])

    def test_evm_contract_dedupe_is_case_insensitive(self):
        first = ProspectRecord("Token", "Ethereum", "0xAbCd", "https://example.org")
        second = ProspectRecord("Different label", "ethereum", "0xabcd", "https://other.example")
        self.assertEqual(first.dedupe_key, second.dedupe_key)

    def test_non_evm_contract_case_is_preserved(self):
        first = ProspectRecord("Token", "Solana", "AbCd")
        second = ProspectRecord("Token", "Solana", "abcd")
        self.assertNotEqual(first.dedupe_key, second.dedupe_key)

    def test_project_key_normalizes_name_and_website_host_on_same_chain(self):
        first = ProspectRecord("  Sample Protocol ", "Base", website_url="https://www.Example.org/path")
        second = ProspectRecord("sample-protocol", "base", website_url="https://example.org/other")
        self.assertEqual(first.dedupe_key, second.dedupe_key)

    def test_fallback_key_keeps_chain_separate(self):
        first = ProspectRecord("Sample Protocol", "Base", website_url="https://example.org")
        second = ProspectRecord("Sample Protocol", "Ethereum", website_url="https://example.org")
        self.assertNotEqual(first.dedupe_key, second.dedupe_key)

    def test_rejects_negative_metric(self):
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            ProspectRecord("Sample", "Base", metrics={"tvl_usd": -1})

    def test_rejects_boolean_as_metric(self):
        with self.assertRaisesRegex(ValueError, "must be a number"):
            ProspectRecord("Sample", "Base", metrics={"tvl_usd": True})

    def test_rejects_non_finite_metric(self):
        for value in (math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                    ProspectRecord("Sample", "Base", metrics={"tvl_usd": value})

    def test_rejects_invalid_website_url(self):
        with self.assertRaisesRegex(ValueError, "http"):
            ProspectRecord("Sample", "Base", website_url="ftp://example.org")


if __name__ == "__main__":
    unittest.main()
