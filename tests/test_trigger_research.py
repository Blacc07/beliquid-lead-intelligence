"""Offline tests for dated RSS/Atom buying-trigger candidates."""
import unittest
from beliquid.trigger_research import collect_trigger_research, research_feed, _parse_timestamp


STAMP = "2026-10-21T12:00:00Z"


class TriggerResearchTests(unittest.TestCase):
    def test_requires_timezone_for_published_timestamp(self):
        self.assertIsNone(_parse_timestamp("2026-10-21T12:00:00"))
        self.assertEqual(_parse_timestamp("2026-10-21T12:00:00Z"), "2026-10-21T12:00:00+00:00")

    def test_feed_match_is_candidate_only_and_dated(self):
        feed = {"feed_url": "https://alpha.example/feed.xml", "entries": [{
            "title": "Alpha announces exchange listing",
            "summary": "The Alpha token will be listed on a new exchange.",
            "url": "https://alpha.example/news/listing",
            "published_at": STAMP,
        }]}
        result = research_feed({"project_name": "Alpha", "token_symbol": "ALPHA", "chain": "ethereum", "contract_address": "0xalpha"},
                               "https://alpha.example/feed.xml", STAMP, lambda url: feed)
        self.assertEqual(result["fetch_status"], "success")
        self.assertEqual(len(result["trigger_candidates"]), 1)
        item = result["trigger_candidates"][0]
        self.assertEqual(item["status"], "candidate_only")
        self.assertTrue(item["date_verified"])
        self.assertEqual(item["trigger_type"], "exchange_listing")

    def test_undated_or_unmatched_entries_do_not_become_verified(self):
        feed = {"feed_url": "https://alpha.example/feed.xml", "entries": [
            {"title": "Alpha announces token launch", "summary": "", "url": "https://alpha.example/news", "published_at": None},
            {"title": "Unrelated project announces token launch", "summary": "", "url": "https://alpha.example/other", "published_at": STAMP},
        ]}
        result = research_feed({"project_name": "Alpha", "token_symbol": "ALPHA", "chain": "ethereum", "contract_address": "0xalpha"},
                               "https://alpha.example/feed.xml", STAMP, lambda url: feed)
        self.assertEqual(len(result["trigger_candidates"]), 1)
        self.assertFalse(result["trigger_candidates"][0]["date_verified"])
        self.assertEqual(result["trigger_candidates"][0]["status"], "candidate_only")

    def test_failed_feed_is_explicit(self):
        result = research_feed({"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha"},
                               "https://alpha.example/feed.xml", STAMP, lambda url: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result["fetch_status"], "fetch_failed")
        self.assertEqual(result["trigger_candidates"], [])

    def test_batch_preserves_unknown_and_outreach_disabled(self):
        prospect = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "token_symbol": "ALPHA"}]}
        public = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "feed_candidates": [{"url": "https://alpha.example/feed.xml"}]}]}
        feed = {"feed_url": "https://alpha.example/feed.xml", "entries": []}
        result = collect_trigger_research(prospect, public, STAMP, lambda url: feed)
        self.assertEqual(result["feeds_succeeded"], 1)
        self.assertEqual(result["trigger_candidates"], 0)
        self.assertEqual(result["records"][0]["buying_trigger_status"], "unknown")
        self.assertFalse(result["outreach_enabled"])
        self.assertFalse(result["canonical_buying_trigger_reviews_changed"])


if __name__ == "__main__":
    unittest.main()
