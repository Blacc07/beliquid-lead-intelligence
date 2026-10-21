"""Offline tests for the GoPlus contract-risk adapter."""
import unittest
from unittest.mock import patch

from beliquid.security_research import collect_security, research_security


class SecurityResearchTests(unittest.TestCase):
    def test_unsupported_chain_stays_unknown_without_request(self):
        result = research_security({"project_name": "X", "chain": "unknown", "contract_address": "0xabc"},
                                   "2026-10-21T12:00:00Z", lambda url: self.fail("must not call API"))
        self.assertEqual(result["fetch_status"], "unsupported_chain")
        self.assertEqual(result["risk_status"], "unknown")

    def test_no_report_is_not_treated_as_safe(self):
        result = research_security({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                   "2026-10-21T12:00:00Z", lambda url: {"code": 1, "result": {}})
        self.assertEqual(result["fetch_status"], "no_report")
        self.assertEqual(result["risk_status"], "unknown")

    def test_high_severity_provider_flag_is_a_concern(self):
        payload = {"code": 1, "result": {"0xabc": {"is_honeypot": "1", "is_mintable": "1"}}}
        result = research_security({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                   "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(result["risk_status"], "concern")
        self.assertIn("is_honeypot", {item["field"] for item in result["findings"]})

    def test_clean_report_is_not_global_clearance(self):
        payload = {"code": 1, "result": {"0xabc": {"is_honeypot": "0", "is_mintable": "0"}}}
        result = research_security({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                   "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["risk_status"], "no_high_risk_flag_detected_by_provider")
        self.assertNotEqual(result["risk_status"], "clear")

    def test_transient_error_retries_then_succeeds(self):
        calls = []
        def requester(url):
            calls.append(url)
            if len(calls) < 3:
                raise TimeoutError("temporary")
            return {"code": 1, "result": {"0xabc": {"is_honeypot": "0"}}}
        with patch("beliquid.security_research.time.sleep"):
            result = research_security({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                       "2026-10-21T12:00:00Z", requester)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["fetch_status"], "success")

    def test_batch_preserves_outreach_disabled(self):
        result = collect_security({"records": [{"project_name": "X", "chain": "unsupported", "contract_address": "0xabc"}]},
                                  "2026-10-21T12:00:00Z")
        self.assertEqual(result["records_exported"], 1)
        self.assertFalse(result["outreach_enabled"])
        self.assertFalse(result["canonical_identity_or_risk_status_changed"])


if __name__ == "__main__":
    unittest.main()
