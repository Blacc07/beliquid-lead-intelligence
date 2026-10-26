"""Offline tests for the GoPlus contract-risk adapter."""
import unittest
from unittest.mock import patch

from beliquid.security_research import SECURITY_CACHE_VERSION, collect_security, research_goplus_solana, research_honeypot_is, research_security


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

    def test_honeypot_is_independent_high_risk_signal_is_concern(self):
        payload = {"honeypotResult": {"isHoneypot": True},
                   "simulationResult": {"buyTax": 2, "sellTax": 3},
                   "contractCode": {"openSource": True}}
        result = research_honeypot_is({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                      "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["provider"], "Honeypot.is token simulation")
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(result["risk_status"], "concern")
        self.assertTrue(result["provider_url"].startswith("https://api.honeypot.is/v2/IsHoneypot?"))

    def test_honeypot_is_failure_stays_unknown(self):
        result = research_honeypot_is({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                      "2026-10-21T12:00:00Z", lambda url: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result["fetch_status"], "fetch_failed")
        self.assertEqual(result["risk_status"], "unknown")

    def test_honeypot_is_high_risk_is_merged_with_goplus_observation(self):
        calls = []
        def requester(url):
            calls.append(url)
            if "gopluslabs" in url:
                return {"code": 1, "result": {"0xabc": {"is_honeypot": "0"}}}
            return {"honeypotResult": {"isHoneypot": True}, "simulationResult": {"sellTax": 1}}
        result = research_security({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                   "2026-10-21T12:00:00Z", requester)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["risk_status"], "concern")
        self.assertEqual(result["independent_provider_count"], 2)
        self.assertEqual(result["independent_sources"][1]["provider"], "Honeypot.is token simulation")

    def test_high_severity_provider_flag_is_a_concern(self):
        payload = {"code": 1, "result": {"0xabc": {"is_honeypot": "1", "is_mintable": "1"}}}
        result = research_security({"project_name": "X", "chain": "base", "contract_address": "0xabc"},
                                   "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(result["risk_status"], "concern")
        self.assertIn("is_honeypot", {item["field"] for item in result["findings"]})
        self.assertEqual(result["criterion_evidence_candidate"]["criterion"], "security_and_reputational_integrity")
        self.assertEqual(result["criterion_evidence_candidate"]["status"], "candidate_only")

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
        self.assertEqual(sum("gopluslabs" in url for url in calls), 3)
        self.assertEqual(len(calls), 4)  # three GoPlus attempts plus independent Honeypot.is request
        self.assertEqual(result["fetch_status"], "success")

    def test_solana_rugcheck_high_risk_report_is_concern(self):
        payload = {"mint": "So111", "riskLevel": "Dangerous", "rugged": False,
                   "risks": [{"name": "Creator history of rugged tokens", "level": "danger", "description": "Creator history of rugged tokens"}],
                   "token": {"mintAuthority": "authority", "freezeAuthority": None}}
        result = research_security({"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"},
                                   "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["provider"], "RugCheck Solana Token Report")
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(result["risk_status"], "concern")
        self.assertTrue(result["provider_url"].startswith("https://api.rugcheck.xyz/v1/tokens/"))
        self.assertEqual(result["criterion_evidence_candidate"]["criterion"], "security_and_reputational_integrity")

    def test_goplus_solana_report_is_recorded_as_independent_source(self):
        payload = {"code": 1, "result": {"So111": {"mint_authority": "authority", "freeze_authority": None}}}
        result = research_goplus_solana({"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"},
                                        "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(result["provider"], "GoPlus Solana Token Security API")
        self.assertEqual(result["risk_status"], "no_high_risk_flag_detected_by_provider")
        self.assertTrue(any(item["field"] == "mint_authority" for item in result["findings"]))

    def test_goplus_solana_missing_report_stays_unknown(self):
        result = research_goplus_solana({"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"},
                                        "2026-10-21T12:00:00Z", lambda url: {"code": 1, "result": {}})
        self.assertEqual(result["fetch_status"], "no_report")
        self.assertEqual(result["risk_status"], "unknown")

    def test_solana_clean_report_is_not_global_clearance(self):
        payload = {"mint": "So111", "riskLevel": "Good", "rugged": False, "risks": [], "score_normalised": 1}
        result = research_security({"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"},
                                   "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["risk_status"], "no_high_risk_flag_detected_by_provider")
        self.assertNotEqual(result["risk_status"], "clear")

    def test_low_liquidity_signal_is_not_misclassified_as_security_hold(self):
        payload = {"mint": "So111", "risks": [{"name": "Low Liquidity", "level": "danger", "description": "Low amount of liquidity in the token pool"}]}
        result = research_security({"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"},
                                   "2026-10-21T12:00:00Z", lambda url: payload)
        self.assertEqual(result["risk_status"], "no_high_risk_flag_detected_by_provider")
        self.assertTrue(any(item["field"] == "risk_item" and item["severity"] == "review" for item in result["findings"]))

    def test_recent_security_result_is_reused(self):
        row = {"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"}
        previous = collect_security({"records": [row]}, "2026-10-21T10:00:00Z",
                                    lambda url: {"mint": "So111", "riskLevel": "Good", "risks": []})
        current = collect_security({"records": [row]}, "2026-10-21T11:00:00Z",
                                   lambda url: self.fail("recent report should be reused"),
                                   previous_payload=previous, cache_ttl_hours=24)
        self.assertTrue(current["records"][0]["reused_from_cache"])
        self.assertEqual(current["records_reused_from_cache"], 1)

    def test_historical_high_risk_concern_survives_clean_later_report(self):
        row = {"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111",
               "identity_risk": {"identity_status": "unknown", "risk_status": "unknown"}}
        previous = collect_security({"records": [row]}, "2026-10-20T10:00:00Z",
                                    lambda url: {"mint": "So111", "rugged": True, "risks": []})
        current = collect_security({"records": [row]}, "2026-10-21T12:00:00Z",
                                   lambda url: {"mint": "So111", "riskLevel": "Good", "rugged": False, "risks": []},
                                   previous_payload=previous, cache_ttl_hours=0)
        self.assertEqual(current["records"][0]["risk_status"], "concern")
        self.assertTrue(current["records"][0]["historical_concern_retained"])
        self.assertEqual(current["records"][0]["criterion_evidence_candidate"]["source_scoped_risk_status"], "concern")

    def test_historical_secondary_provider_concern_keeps_finding_provenance(self):
        row = {"project_name": "Token", "chain": "base", "contract_address": "0xabc"}
        previous = collect_security({"records": [row]}, "2026-10-20T10:00:00Z",
                                    lambda url: {"code": 1, "result": {"0xabc": {"is_honeypot": "0"}}})
        prior = previous["records"][0]
        prior["risk_status"] = "concern"
        prior["independent_sources"] = [
            {"provider": "GoPlus Token Security API", "provider_url": "https://api.gopluslabs.io/report",
             "observed_at": "2026-10-20T10:00:00Z", "risk_status": "no_high_risk_flag_detected_by_provider", "findings": []},
            {"provider": "Honeypot.is token simulation", "provider_url": "https://api.honeypot.is/report",
             "observed_at": "2026-10-20T10:00:00Z", "risk_status": "concern",
             "findings": [{"field": "isHoneypot", "severity": "high", "value": "true"}]},
        ]
        current = collect_security({"records": [row]}, "2026-10-21T12:00:00Z",
                                   lambda url: {"code": 1, "result": {"0xabc": {"is_honeypot": "0"}}},
                                   previous_payload=previous, cache_ttl_hours=0)
        record = current["records"][0]
        self.assertTrue(record["historical_concern_retained"])
        self.assertIn("isHoneypot", {item.get("field") for item in record["findings"]})
        self.assertTrue(any(item.get("provider") == "Honeypot.is token simulation"
                            for item in record["historical_concern_sources"]))

    def test_explicit_canonical_clearance_forces_fresh_check_of_cached_concern(self):
        row = {"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111",
               "identity_risk": {"identity_status": "verified", "risk_status": "clear"}}
        previous = collect_security({"records": [row]}, "2026-10-21T10:00:00Z",
                                    lambda url: {"mint": "So111", "rugged": True, "risks": []})
        current = collect_security({"records": [row]}, "2026-10-21T11:00:00Z",
                                   lambda url: {"mint": "So111", "riskLevel": "Good", "rugged": False, "risks": []},
                                   previous_payload=previous, cache_ttl_hours=24)
        self.assertEqual(current["records"][0]["risk_status"], "no_high_risk_flag_detected_by_provider")
        self.assertFalse(current["records"][0].get("reused_from_cache", False))

    def test_cache_version_change_forces_security_refresh(self):
        row = {"project_name": "SolanaToken", "chain": "solana", "contract_address": "So111"}
        payload = {"mint": "So111", "riskLevel": "Good", "risks": []}
        previous = collect_security({"records": [row]}, "2026-10-21T10:00:00Z", lambda url: payload)
        previous["records"][0]["cache_version"] = SECURITY_CACHE_VERSION - 1
        current = collect_security({"records": [row]}, "2026-10-21T11:00:00Z", lambda url: payload,
                                   previous_payload=previous, cache_ttl_hours=24)
        self.assertEqual(current["records_fetched_this_run"], 1)
        self.assertFalse(current["records"][0]["reused_from_cache"])

    def test_batch_preserves_outreach_disabled(self):
        result = collect_security({"records": [{"project_name": "X", "chain": "unsupported", "contract_address": "0xabc"}]},
                                  "2026-10-21T12:00:00Z")
        self.assertEqual(result["records_exported"], 1)
        self.assertFalse(result["outreach_enabled"])
        self.assertFalse(result["canonical_identity_or_risk_status_changed"])


if __name__ == "__main__":
    unittest.main()
