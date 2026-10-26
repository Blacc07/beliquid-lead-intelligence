"""Offline tests for chain-explorer identity cross-checking."""
import unittest

from beliquid.identity_crosscheck import crosscheck_record, collect_identity_crosschecks


STAMP = "2026-10-26T12:00:00Z"


class IdentityCrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.prospect = {"project_name": "Alpha Protocol", "token_symbol": "ALPHA", "chain": "base",
                         "contract_address": "0xabc123456789abcdef", "website_url_candidate": "https://alpha.example"}
        self.public = {"candidate_website_url": "https://alpha.example",
                       "page": {"contract_address_mentioned": True},
                       "source_candidates": [
                           {"url": "https://alpha.example", "label": "Alpha Protocol"},
                           {"url": "https://x.com/AlphaProtocol", "label": "X"},
                           {"url": "https://alpha.example/contact", "label": "Contact"},
                       ]}

    def test_strong_cross_source_match_is_candidate_not_canonical_verification(self):
        def fetcher(url):
            self.assertEqual(url, "https://basescan.org/token/0xabc123456789abcdef")
            return {"final_url": url, "page_title": "Alpha Protocol ALPHA Token",
                    "meta_description": "ALPHA token contract", "text_excerpt": "Contract verified",
                    "links": [{"href": "https://alpha.example", "text": "Website"},
                              {"href": "https://basescan.org/address/0xabc123456789abcdef", "text": "Contract"}]}
        result = crosscheck_record(self.prospect, self.public, STAMP, fetcher)
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(result["identity_candidate_assessment"]["status"], "corroborated_candidate")
        self.assertEqual(result["chain_identifier"], "8453")
        self.assertFalse(result["canonical_identity_status_changed"])
        self.assertFalse(result["canonical_risk_status_changed"])
        self.assertFalse(result["outreach_enabled"])

    def test_missing_contract_mention_or_domain_conflict_stays_unresolved(self):
        public = {**self.public, "page": {"contract_address_mentioned": False}}
        result = crosscheck_record(self.prospect, public, STAMP,
            lambda url: {"final_url": url, "page_title": "Other Token OTHER", "text_excerpt": "Metadata",
                         "links": [{"href": "https://different.example", "text": "Website"}]})
        self.assertEqual(result["identity_candidate_assessment"]["status"], "unresolved")
        self.assertTrue(result["identity_candidate_assessment"]["conflicts"])
        self.assertFalse(result["canonical_identity_status_changed"])

    def test_unsupported_chain_and_fetch_failure_remain_unknown(self):
        unsupported = crosscheck_record({**self.prospect, "chain": "robinhood"}, self.public, STAMP,
                                        lambda url: self.fail("unsupported chain must not fetch"))
        self.assertEqual(unsupported["fetch_status"], "unsupported_chain")
        failed = crosscheck_record(self.prospect, self.public, STAMP,
                                   lambda url: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(failed["fetch_status"], "fetch_failed")
        self.assertEqual(failed["identity_candidate_assessment"]["status"], "unresolved")

    def test_batch_exports_one_result_per_prospect(self):
        result = collect_identity_crosschecks({"records": [self.prospect]},
            {"records": [{"chain": "base", "contract_address": self.prospect["contract_address"], **self.public}]},
            STAMP, lambda url: {"final_url": url, "page_title": "ALPHA Token",
                                "links": [{"href": "https://alpha.example", "text": "Website"}]})
        self.assertEqual(result["records_exported"], 1)
        self.assertFalse(result["canonical_identity_status_changed"])
        self.assertFalse(result["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
