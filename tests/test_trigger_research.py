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
        self.assertEqual(len(result["trigger_candidates"]), 0)
        self.assertEqual(result["undated_matches"], 1)

    def test_failed_feed_is_explicit(self):
        result = research_feed({"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha"},
                               "https://alpha.example/feed.xml", STAMP, lambda url: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result["fetch_status"], "fetch_failed")
        self.assertEqual(result["trigger_candidates"], [])

    def test_recent_successful_feed_is_reused(self):
        prospect = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "token_symbol": "ALPHA"}]}
        public = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "feed_candidates": [{"url": "https://alpha.example/feed.xml"}]}]}
        feed = {"feed_url": "https://alpha.example/feed.xml", "entries": []}
        first = collect_trigger_research(prospect, public, "2026-10-21T10:00:00Z", lambda url: feed, global_feeds=[])
        second = collect_trigger_research(prospect, public, "2026-10-21T11:00:00Z",
                                          lambda url: self.fail("recent feed should be reused"),
                                          previous_payload=first, cache_ttl_hours=24, global_feeds=[])
        self.assertEqual(second["feeds_reused_from_cache"], 1)
        self.assertEqual(second["feeds_attempted"], 0)
        self.assertEqual(second["feeds_processed"], 1)

    def test_cache_version_change_forces_feed_refresh(self):
        prospect = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "token_symbol": "ALPHA"}]}
        public = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "feed_candidates": [{"url": "https://alpha.example/feed.xml"}]}]}
        feed = {"feed_url": "https://alpha.example/feed.xml", "entries": []}
        first = collect_trigger_research(prospect, public, "2026-10-21T10:00:00Z", lambda url: feed, global_feeds=[])
        first["records"][0]["feed_results"][0]["cache_version"] = 1
        second = collect_trigger_research(prospect, public, "2026-10-21T11:00:00Z", lambda url: feed,
                                          previous_payload=first, cache_ttl_hours=24, global_feeds=[])
        self.assertEqual(second["feeds_attempted"], 1)
        self.assertEqual(second["feeds_reused_from_cache"], 0)

    def test_global_news_feed_discovers_dated_candidates_without_project_feed(self):
        prospect = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "token_symbol": "ALPHA"}]}
        public = {"records": []}
        feed = {"feed_url": "https://news.example/rss", "entries": [{
            "title": "Alpha announces exchange listing",
            "summary": "Alpha will be listed on an exchange",
            "url": "https://news.example/alpha-listing",
            "published_at": STAMP,
        }]}
        result = collect_trigger_research(prospect, public, STAMP, lambda url: feed,
                                          global_feeds=[{"url": "https://news.example/rss", "provider": "ExampleNews"}])
        self.assertEqual(result["feeds_attempted"], 1)
        self.assertEqual(result["trigger_candidates"], 1)
        candidate = result["records"][0]["trigger_candidates"][0]
        self.assertEqual(candidate["source_scope"], "global_news")
        self.assertEqual(candidate["status"], "candidate_only")
        self.assertTrue(candidate["date_verified"])
        self.assertFalse(result["canonical_buying_trigger_reviews_changed"])

    def test_batch_preserves_unknown_and_outreach_disabled(self):
        prospect = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "token_symbol": "ALPHA"}]}
        public = {"records": [{"project_name": "Alpha", "chain": "ethereum", "contract_address": "0xalpha", "feed_candidates": [{"url": "https://alpha.example/feed.xml"}]}]}
        feed = {"feed_url": "https://alpha.example/feed.xml", "entries": []}
        result = collect_trigger_research(prospect, public, STAMP, lambda url: feed, global_feeds=[])
        self.assertEqual(result["feeds_succeeded"], 1)
        self.assertEqual(result["trigger_candidates"], 0)
        self.assertEqual(result["records"][0]["buying_trigger_status"], "unknown")
        self.assertFalse(result["outreach_enabled"])
        self.assertFalse(result["canonical_buying_trigger_reviews_changed"])


if __name__ == "__main__":
    unittest.main()
