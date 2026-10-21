"""Offline tests for automated public-page evidence candidate collection."""
import unittest
from beliquid.automated_research import collect_research, research_record, _public_http_url


class AutomatedResearchTests(unittest.TestCase):
    def test_recent_successful_page_is_reused_for_unchanged_prospect(self):
        payload = {"records": [{"project_name": "Cached", "chain": "base", "contract_address": "0xcached", "website_url_candidate": "https://example.org"}]}
        page = {"final_url": "https://example.org", "text_excerpt": "Official site", "links": [], "feed_links": []}
        first = collect_research(payload, "2026-10-21T10:00:00Z", lambda url: page)
        second = collect_research(payload, "2026-10-21T11:00:00Z", lambda url: self.fail("cache should be reused"),
                                  previous_payload=first, cache_ttl_hours=24)
        self.assertTrue(second["records"][0]["reused_from_cache"])
        self.assertEqual(second["records_reused_from_cache"], 1)

    def test_cache_version_change_forces_public_page_refresh(self):
        payload = {"records": [{"project_name": "Cached", "chain": "base", "contract_address": "0xcached", "website_url_candidate": "https://example.org"}]}
        page = {"final_url": "https://example.org", "text_excerpt": "Cached", "links": [], "feed_links": []}
        first = collect_research(payload, "2026-10-21T10:00:00Z", lambda url: page)
        first["records"][0]["cache_version"] = 1
        second = collect_research(payload, "2026-10-21T11:00:00Z", lambda url: page,
                                  previous_payload=first, cache_ttl_hours=24)
        self.assertFalse(second["records"][0]["reused_from_cache"])
        self.assertEqual(second["records_fetched_this_run"], 1)

    def test_private_and_non_http_urls_are_rejected(self):
        self.assertIsNone(_public_http_url("file:///etc/passwd"))
        self.assertIsNone(_public_http_url("http://127.0.0.1/admin"))
        self.assertIsNone(_public_http_url("http://localhost/"))

    def test_no_candidate_website_preserves_unknown_states(self):
        result = research_record({"project_name": "Token", "chain": "base", "contract_address": "0xabc"}, "2026-10-21T12:00:00Z")
        self.assertEqual(result["fetch_status"], "no_website_candidate")
        self.assertEqual(result["identity_status"], "unknown")
        self.assertEqual(result["risk_status"], "unknown")
        self.assertFalse(result["outreach_enabled"])

    def test_failed_fetch_is_auditable_and_does_not_clear_risk(self):
        def fail(url):
            raise TimeoutError("slow")
        result = research_record({"project_name": "Token", "chain": "base", "contract_address": "0xabc", "website_url_candidate": "https://example.org"}, "2026-10-21T12:00:00Z", fail)
        self.assertEqual(result["fetch_status"], "fetch_failed")
        self.assertEqual(result["identity_status"], "unknown")
        self.assertEqual(result["risk_status"], "unknown")

    def test_page_text_generates_candidates_not_qualification_findings(self):
        page = {"final_url": "https://example.org/", "page_title": "Example", "meta_description": "Token",
                "og_site_name": "Example", "text_excerpt": "We are launching a new exchange listing with liquidity and partnerships. 0xabc",
                "links": [{"url": "https://github.com/example/project", "label": "GitHub"}]}
        result = research_record({"project_name": "Token", "chain": "base", "contract_address": "0xabc", "website_url_candidate": "https://example.org"}, "2026-10-21T12:00:00Z", lambda url: page)
        self.assertEqual(result["fetch_status"], "success")
        self.assertTrue(result["page"]["contract_address_mentioned"])
        self.assertTrue(any(item["term"] == "listing" for item in result["trigger_candidates"]))
        self.assertTrue(all(item["status"] == "candidate_only" for item in result["trigger_candidates"]))
        self.assertEqual(result["identity_status"], "unknown")
        self.assertEqual(result["risk_status"], "unknown")
        self.assertEqual(result["identity_candidate_assessment"]["status"], "unresolved")
        self.assertFalse(result["identity_candidate_assessment"]["score_is_probability"])
        self.assertEqual(result["qualification_status"], "not_assessed")
        criteria = {item["criterion"] for item in result["criterion_evidence_candidates"]}
        self.assertTrue({"service_fit_and_demonstrated_need", "market_activity_and_commercial_potential", "buying_trigger_and_timing", "project_credibility_and_team_access", "growth_and_strategic_potential"}.issubset(criteria))
        self.assertTrue(all(item["status"] == "candidate_only" for item in result["criterion_evidence_candidates"]))
        self.assertFalse(result["outreach_enabled"])

    def test_identity_candidate_mismatch_is_recorded_without_auto_verification(self):
        record = {"project_name": "Expected Project", "token_symbol": "EXPT", "chain": "base",
                  "contract_address": "0xabc", "website_url_candidate": "https://example.org"}
        page = {"final_url": "https://example.org/", "page_title": "Different Project",
                "og_site_name": "Different", "meta_description": "Another project", "text_excerpt": "A separate product",
                "links": [], "feed_links": []}
        result = research_record(record, "2026-10-21T12:00:00Z", lambda url: page)
        assessment = result["identity_candidate_assessment"]
        self.assertEqual(assessment["status"], "unresolved")
        self.assertTrue(any(item["type"] == "candidate_name_or_symbol_not_matched" for item in assessment["conflicts"]))
        self.assertEqual(result["identity_status"], "unknown")

    def test_batch_counts_are_reconciled(self):
        payload = {"records": [{"project_name": "A", "chain": "base", "contract_address": "a"},
                               {"project_name": "B", "chain": "base", "contract_address": "b", "website_url_candidate": "https://example.org"}]}
        result = collect_research(payload, "2026-10-21T12:00:00Z", lambda url: {"final_url": url, "page_title": "", "meta_description": "", "og_site_name": "", "text_excerpt": "", "links": []})
        self.assertEqual(result["records_exported"], 2)
        self.assertEqual(result["records_without_website_candidate"], 1)
        self.assertEqual(result["records_with_page_fetched"], 1)
        self.assertFalse(result["outreach_enabled"])


if __name__ == "__main__":
    unittest.main()
