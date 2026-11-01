import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness.db import build_db
from evalharness.gold import generate_gold
from evalharness.judge import calibrate, cohens_kappa, judge, kappa_bootstrap_ci
from evalharness.metrics import evaluate_system
from evalharness.regression_gate import check
from evalharness.run_eval import render_report, run
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

    def test_kappa_bootstrap_ci_brackets_point_estimate(self):
        with open(os.path.join(ROOT, "data", "human_labels.jsonl")) as f:
            labels = [json.loads(line) for line in f]
        result = calibrate(labels)
        lo, hi = result["cohens_kappa_bootstrap_95ci"]
        self.assertLessEqual(lo, result["cohens_kappa"])
        self.assertGreaterEqual(hi, result["cohens_kappa"])
        self.assertGreaterEqual(lo, -1.0)
        self.assertLessEqual(hi, 1.0)
        # With only 44 labels the interval must be honestly wide, not a
        # point: the judge's agreement is not known to a hair's breadth.
        self.assertGreater(hi - lo, 0.1)

    def test_kappa_bootstrap_ci_is_reproducible_and_degenerate_safe(self):
        pairs = [("correct", "correct"), ("incorrect", "incorrect")] * 5
        self.assertEqual(kappa_bootstrap_ci(pairs, n_boot=200),
                         kappa_bootstrap_ci(pairs, n_boot=200))
        self.assertEqual(kappa_bootstrap_ci(pairs, n_boot=200), (1.0, 1.0))
        self.assertEqual(kappa_bootstrap_ci([]), (0.0, 0.0))

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


class TestPerDifficultyBreakdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(runs=1)

    def test_per_difficulty_counts_cover_gold_set(self):
        by_diff = self.res["per_difficulty"]
        self.assertEqual(sum(v["n"] for v in by_diff.values()),
                         self.res["gold_size"])
        for v in by_diff.values():
            self.assertGreater(v["n"], 0)
            self.assertGreaterEqual(v["system_a_accuracy"], 0.0)
            self.assertLessEqual(v["system_a_accuracy"], 1.0)
            self.assertGreaterEqual(v["system_b_accuracy"], 0.0)
            self.assertLessEqual(v["system_b_accuracy"], 1.0)

    def test_per_difficulty_matches_record_counts(self):
        # Recompute from the per-system records: the breakdown must agree
        # with the underlying per-question results, not just sum correctly.
        records = self.res["systems"]["system_a"]["records"]
        for diff, v in self.res["per_difficulty"].items():
            subset = [r for r in records if r["difficulty"] == diff]
            self.assertEqual(len(subset), v["n"])
            expected = (sum(r["execution_correct"] for r in subset) / len(subset))
            self.assertAlmostEqual(v["system_a_accuracy"], expected)

    def test_report_contains_per_difficulty_table(self):
        report = render_report(self.res)
        self.assertIn("## Per-difficulty accuracy", report)
        for diff in self.res["per_difficulty"]:
            self.assertIn(f"| {diff} |", report)


if __name__ == "__main__":
    unittest.main()
