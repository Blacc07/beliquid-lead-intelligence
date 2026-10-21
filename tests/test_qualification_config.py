import json
from pathlib import Path
import unittest


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "qualification_criteria.json"


class QualificationCriteriaConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_config_is_explicitly_draft_and_not_live(self):
        self.assertEqual(self.config["status"], "draft_requires_business_approval")
        self.assertIn("not connected to live scoring", self.config["purpose"])

    def test_criteria_have_unique_keys_and_positive_weights_totaling_100(self):
        criteria = self.config["criteria"]
        keys = [item["key"] for item in criteria]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(item["weight"] > 0 for item in criteria))
        self.assertEqual(sum(item["weight"] for item in criteria), 100)

    def test_each_criterion_has_definitions_and_unknown_policy(self):
        for item in self.config["criteria"]:
            with self.subTest(criterion=item["key"]):
                self.assertTrue(item["label"].strip())
                self.assertTrue(item["positive_definition"].strip())
                self.assertTrue(item["unknown_when"].strip())

    def test_safety_and_scoring_safeguards_are_enabled(self):
        rules = self.config["rules"]
        self.assertTrue(rules["unknown_is_not_zero"])
        self.assertTrue(rules["market_metrics_alone_are_not_buying_intent"])
        self.assertTrue(rules["promotion_or_boosting_is_not_a_quality_signal"])
        self.assertTrue(rules["no_automated_outreach"])
        self.assertGreaterEqual(self.config["minimum_evidence_coverage_percent"], 60)


if __name__ == "__main__":
    unittest.main()
