"""Tests for Telegram lead digest formatting."""
import unittest

from beliquid.telegram_digest import build_digest


class TelegramDigestTests(unittest.TestCase):
    def test_digest_labels_candidates_and_withheld_scores(self):
        message = build_digest({
            "qualification_summary": {"scores_issued": 0},
            "records": [{
                "project_name": "Alpha Protocol",
                "token_symbol": "ALPHA",
                "chain": "base",
                "contract_address": "0xabc123",
                "website_url_candidate": "https://alpha.example",
                "market_research_priority": {"priority": "high"},
                "action_route": "research",
                "qualification": {"score_percent": None},
            }],
        }, "https://github.com/example/repo/actions/runs/123")
        self.assertIn("Research candidates, not verified leads", message)
        self.assertIn("Alpha Protocol", message)
        self.assertIn("Qualification: withheld", message)
        self.assertIn("Candidate site:", message)
        self.assertIn("No prospect outreach is sent.", message)
        self.assertIn("workflow run and artifacts", message)

    def test_empty_batch_is_explicit(self):
        message = build_digest({"records": []}, "")
        self.assertIn("Candidates generated: <b>0</b>", message)
        self.assertIn("No candidates were generated", message)

    def test_candidate_names_are_html_escaped(self):
        message = build_digest({"records": [{
            "project_name": "<script>alert(1)</script>",
            "qualification": {},
        }]}, "")
        self.assertNotIn("<script>", message)
        self.assertIn("&lt;script&gt;", message)


if __name__ == "__main__":
    unittest.main()
