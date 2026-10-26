"""Tests for source-backed automatic task-ledger generation."""
import unittest

from beliquid.task_ledger import build_task_ledger


STAMP = "2026-10-21T12:00:00Z"


def prospect(name, market_value=123.0):
    return {
        "project_name": name,
        "chain": "ethereum",
        "contract_address": "0x" + name.lower(),
        "evidence": [{
            "evidence_type": "token_market_enrichment",
            "source_url": "https://dexscreener.com/token/" + name.lower(),
            "observed_at": STAMP,
        }],
        "metrics": {"volume_24h_usd": market_value},
    }


class TaskLedgerTests(unittest.TestCase):
    def test_records_only_tasks_with_successful_source_evidence(self):
        row = prospect("alpha")
        public = {"records": [{
            "project_name": "alpha", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "success", "observed_at": STAMP,
            "page": {"final_url": "https://alpha.example/"},
        }]}
        security = {"records": [{
            "project_name": "alpha", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "fetch_failed", "provider_url": "https://api.gopluslabs.io/api/v1/token_security/1",
            "observed_at": STAMP,
        }]}
        trigger = {"records": [{
            "project_name": "alpha", "chain": "ethereum", "contract_address": row["contract_address"],
            "feeds_succeeded": 1, "feed_results": [{"fetch_status": "success", "final_feed_url": "https://alpha.example/feed.xml", "observed_at": STAMP}],
        }]}
        result = build_task_ledger({"records": [row]}, public, security, STAMP, trigger)
        tasks = result["reviews"]["ethereum:0xalpha"]
        self.assertIn("verify_identity_and_risk", tasks)
        self.assertIn("investigate_market_quality", tasks)
        self.assertIn("research_buying_triggers", tasks)
        self.assertNotIn("complete_criterion_evidence", tasks)
        self.assertEqual(tasks["verify_identity_and_risk"]["outcome"], "inconclusive")
        self.assertEqual(tasks["verify_identity_and_risk"]["evidence_urls"], ["https://alpha.example/"])
        self.assertEqual(tasks["investigate_market_quality"]["outcome"], "completed")
        self.assertFalse(result["policy"]["identity_and_risk_clearance_changed"])
        self.assertFalse(result["policy"]["outreach_enabled"])

    def test_failed_or_unsupported_sources_do_not_complete_identity_task(self):
        row = prospect("beta", None)
        public = {"records": [{
            "project_name": "beta", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "fetch_failed", "observed_at": STAMP, "page": None,
        }]}
        security = {"records": [{
            "project_name": "beta", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "unsupported_chain", "provider_url": None, "observed_at": STAMP,
        }]}
        result = build_task_ledger({"records": [row]}, public, security, STAMP)
        tasks = result["reviews"]["ethereum:0xbeta"]
        self.assertNotIn("verify_identity_and_risk", tasks)
        self.assertIn("investigate_market_quality", tasks)
        self.assertNotIn("research_buying_triggers", tasks)

    def test_explicit_no_report_is_an_inconclusive_completed_attempt_not_clearance(self):
        row = prospect("gamma")
        security = {"records": [{
            "project_name": "gamma", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "no_report", "provider_url": "https://api.gopluslabs.io/api/v1/token_security/1",
            "observed_at": STAMP,
        }]}
        result = build_task_ledger({"records": [row]}, {"records": []}, security, STAMP)
        tasks = result["reviews"]["ethereum:0xgamma"]
        self.assertEqual(tasks["verify_identity_and_risk"]["outcome"], "inconclusive")
        self.assertEqual(tasks["verify_identity_and_risk"]["evidence_urls"], ["https://api.gopluslabs.io/api/v1/token_security/1"])
        self.assertFalse(result["policy"]["identity_and_risk_clearance_changed"])

    def test_prior_completions_persist_when_current_sources_fail(self):
        row = prospect("persist")
        public = {"records": [{
            "project_name": "persist", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "success", "observed_at": STAMP,
            "page": {"final_url": "https://persist.example/"},
        }]}
        security = {"records": [{
            "project_name": "persist", "chain": "ethereum", "contract_address": row["contract_address"],
            "fetch_status": "no_report", "provider_url": "https://security.example/report",
            "observed_at": STAMP,
        }]}
        trigger = {"records": [{
            "project_name": "persist", "chain": "ethereum", "contract_address": row["contract_address"],
            "feed_results": [{"fetch_status": "success", "final_feed_url": "https://persist.example/feed.xml", "observed_at": STAMP}],
        }]}
        first = build_task_ledger({"records": [row]}, public, security, STAMP, trigger)
        second = build_task_ledger({"records": [row]}, {"records": []}, {"records": []},
                                   "2026-10-22T12:00:00Z", {"records": []}, previous_payload=first)
        tasks = second["reviews"]["ethereum:0xpersist"]
        self.assertIn("verify_identity_and_risk", tasks)
        self.assertIn("investigate_market_quality", tasks)
        self.assertIn("research_buying_triggers", tasks)
        self.assertEqual(tasks["verify_identity_and_risk"]["input_fingerprint"],
                         first["reviews"]["ethereum:0xpersist"]["verify_identity_and_risk"]["input_fingerprint"])

    def test_task_history_survives_batch_absence_and_can_be_reused(self):
        row = prospect("history")
        public = {"records": [{"project_name": "history", "chain": "ethereum",
            "contract_address": row["contract_address"], "fetch_status": "success",
            "observed_at": STAMP, "page": {"final_url": "https://history.example/"}}]}
        security = {"records": []}
        first = build_task_ledger({"records": [row]}, public, security, STAMP)
        absent = build_task_ledger({"records": []}, {"records": []}, {"records": []},
                                   "2026-10-22T12:00:00Z", previous_payload=first)
        key = "ethereum:0xhistory"
        self.assertNotIn(key, absent["reviews"])
        self.assertIn(key, absent["historical_reviews"])
        returned = build_task_ledger({"records": [row]}, {"records": []}, {"records": []},
                                     "2026-10-23T12:00:00Z", previous_payload=absent)
        self.assertIn(key, returned["reviews"])
        self.assertEqual(returned["reviews"][key]["verify_identity_and_risk"]["input_fingerprint"],
                         first["reviews"][key]["verify_identity_and_risk"]["input_fingerprint"])
        self.assertNotIn(key, returned["historical_reviews"])

    def test_ledger_rejects_duplicate_source_records(self):
        row = prospect("delta")
        duplicate = {"records": [{"chain": "ethereum", "contract_address": row["contract_address"]}] * 2}
        with self.assertRaisesRegex(ValueError, "duplicate automated public research"):
            build_task_ledger({"records": [row]}, duplicate, None, STAMP)


if __name__ == "__main__":
    unittest.main()
