import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness.db import build_db
from evalharness.gold import generate_gold
from evalharness.judge import calibrate, cohens_kappa, judge
from evalharness.metrics import evaluate_system
from evalharness.regression_gate import check
from evalharness.systems import system_a, system_b

ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestSystems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = build_db()
        cls.gold = generate_gold()

    def test_gold_set_size_and_diversity(self):
        self.assertGreaterEqual(len(self.gold), 48)
        self.assertGreaterEqual(len({g["category"] for g in self.gold}), 8)

    def test_system_b_beats_system_a_materially(self):
        a = evaluate_system(self.conn, system_a, self.gold)
        b = evaluate_system(self.conn, system_b, self.gold)
        self.assertGreaterEqual(b["execution_accuracy"], 0.85)
        self.assertGreater(b["execution_accuracy"], a["execution_accuracy"] + 0.2)

    def test_checked_in_gold_matches_generator(self):
        with open(os.path.join(ROOT, "data", "gold.jsonl")) as f:
            checked = [json.loads(line) for line in f]
        self.assertEqual(len(checked), len(self.gold))
        self.assertEqual(checked[0]["gold_sql"], self.gold[0]["gold_sql"])


class TestJudge(unittest.TestCase):
    def test_judge_accepts_matching_headline_number(self):
        self.assertEqual(judge("There were 360 orders.", "360 orders total."), "correct")
        self.assertEqual(judge("There were 360 orders.", "320 orders total."), "incorrect")

    def test_kappa_perfect_agreement(self):
        pairs = [("correct", "correct"), ("incorrect", "incorrect")] * 5
        self.assertAlmostEqual(cohens_kappa(pairs), 1.0)

    def test_calibration_on_checked_in_labels(self):
        with open(os.path.join(ROOT, "data", "human_labels.jsonl")) as f:
            labels = [json.loads(line) for line in f]
        self.assertGreaterEqual(len(labels), 30)
        result = calibrate(labels)
        conf = result["confusion"]
        self.assertEqual(conf["tp"] + conf["fp"] + conf["fn"] + conf["tn"], len(labels))
        # The naive judge should show real but imperfect agreement,
        # including designed disagreements in both directions.
        self.assertGreater(result["cohens_kappa"], 0.3)
        self.assertLess(result["cohens_kappa"], 0.9)
        self.assertGreater(conf["fp"], 0)
        self.assertGreater(conf["fn"], 0)


class TestRegressionGate(unittest.TestCase):
    def test_gate_passes_within_tolerance(self):
        self.assertTrue(check(0.99, 1.0))
        self.assertTrue(check(0.98, 1.0))

    def test_gate_fails_on_big_drop(self):
        self.assertFalse(check(0.90, 1.0))


if __name__ == "__main__":
    unittest.main()
