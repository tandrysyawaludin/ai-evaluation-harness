"""Split-half reliability: per-system accuracy on each half of the gold set."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness import run_eval
from evalharness.run_eval import build_split_half, render_report, run


def _gold(qid):
    return {"id": qid, "category": "count_total", "difficulty": "easy"}


def _rec(qid, correct):
    return {"id": qid, "execution_correct": correct}


class TestBuildSplitHalf(unittest.TestCase):
    def test_interleaved_split_and_accuracies(self):
        # 4 questions, interleaved: half_1 = q1, q3; half_2 = q2, q4.
        gold = [_gold(f"q{i}") for i in range(1, 5)]
        a = [_rec("q1", True), _rec("q2", False),
             _rec("q3", True), _rec("q4", False)]
        b = [_rec("q1", True), _rec("q2", True),
             _rec("q3", False), _rec("q4", True)]
        s = build_split_half(gold, a, b)
        self.assertEqual(s["halves"]["half_1"]["n"], 2)
        self.assertEqual(s["halves"]["half_2"]["n"], 2)
        # half_1: A 2/2, B 1/2, B-A -0.5; half_2: A 0/2, B 2/2, B-A +1.0.
        self.assertEqual(s["halves"]["half_1"]["system_a_accuracy"], 1.0)
        self.assertEqual(s["halves"]["half_1"]["system_b_accuracy"], 0.5)
        self.assertEqual(s["halves"]["half_1"]
                         ["accuracy_difference_b_minus_a"], -0.5)
        self.assertEqual(s["halves"]["half_2"]["system_a_accuracy"], 0.0)
        self.assertEqual(s["halves"]["half_2"]["system_b_accuracy"], 1.0)
        self.assertEqual(s["halves"]["half_2"]
                         ["accuracy_difference_b_minus_a"], 1.0)
        self.assertEqual(s["gap"]["system_a"], 1.0)
        self.assertEqual(s["gap"]["system_b"], 0.5)
        self.assertEqual(s["gap"]["accuracy_difference_b_minus_a"], 1.5)
        self.assertEqual(s["balance_threshold"], 0.05)
        self.assertFalse(s["balanced"])

    def test_balanced_when_halves_agree(self):
        gold = [_gold(f"q{i}") for i in range(1, 5)]
        a = [_rec(f"q{i}", True) for i in range(1, 5)]
        b = [_rec(f"q{i}", True) for i in range(1, 5)]
        s = build_split_half(gold, a, b)
        self.assertEqual(s["gap"], {"system_a": 0.0, "system_b": 0.0,
                                    "accuracy_difference_b_minus_a": 0.0})
        self.assertTrue(s["balanced"])

    def test_odd_gold_set_splits_unevenly(self):
        gold = [_gold(f"q{i}") for i in range(1, 6)]
        a = [_rec(f"q{i}", True) for i in range(1, 6)]
        b = [_rec(f"q{i}", False) for i in range(1, 6)]
        s = build_split_half(gold, a, b)
        self.assertEqual(s["halves"]["half_1"]["n"], 3)
        self.assertEqual(s["halves"]["half_2"]["n"], 2)
        self.assertEqual(s["halves"]["half_1"]["system_a_accuracy"], 1.0)
        self.assertEqual(s["halves"]["half_2"]["system_b_accuracy"], 0.0)

    def test_count_mismatch_raises(self):
        gold = [_gold("q1"), _gold("q2")]
        a = [_rec("q1", True)]
        b = [_rec("q1", True), _rec("q2", True)]
        with self.assertRaises(ValueError):
            build_split_half(gold, a, b)

    def test_id_misalignment_raises(self):
        gold = [_gold("q1"), _gold("q2")]
        a = [_rec("q1", True), _rec("qX", True)]
        b = [_rec("q1", True), _rec("q2", True)]
        with self.assertRaises(ValueError):
            build_split_half(gold, a, b)


class TestRunSplitHalf(unittest.TestCase):
    def test_run_carries_split_half(self):
        res = run(runs=1, seed=42)
        s = res["split_half"]
        h1, h2 = s["halves"]["half_1"], s["halves"]["half_2"]
        # The halves partition the gold set, and their correct counts
        # add up to the headline numbers.
        self.assertEqual(h1["n"] + h2["n"], res["gold_size"])
        self.assertEqual(h1["n"], (res["gold_size"] + 1) // 2)
        self.assertEqual(h2["n"], res["gold_size"] // 2)
        for name in ("system_a", "system_b"):
            total = (h1[f"{name}_correct"] + h2[f"{name}_correct"])
            self.assertEqual(total, res["systems"][name]["correct"])
        self.assertEqual(s["balance_threshold"], 0.05)
        self.assertEqual(s["balanced"],
                         all(v <= 0.05 for v in s["gap"].values()))

    def test_real_gold_set_half_accuracies(self):
        # system_b is 100% on the real gold set, so both its halves are
        # 100% and its gap is 0; system_a's gap is the interesting one.
        res = run(runs=1, seed=42)
        s = res["split_half"]
        self.assertEqual(s["halves"]["half_1"]["system_b_accuracy"], 1.0)
        self.assertEqual(s["halves"]["half_2"]["system_b_accuracy"], 1.0)
        self.assertEqual(s["gap"]["system_b"], 0.0)

    def test_report_renders_split_half_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Split-half reliability", report)
        s = res["split_half"]
        h1, h2 = s["halves"]["half_1"], s["halves"]["half_2"]
        self.assertIn(
            f"| Half 1 | {h1['n']} | "
            f"{h1['system_a_accuracy']:.1%} "
            f"({h1['system_a_correct']}/{h1['n']}) | "
            f"{h1['system_b_accuracy']:.1%} "
            f"({h1['system_b_correct']}/{h1['n']}) | "
            f"{h1['accuracy_difference_b_minus_a']:+.1%} |", report)
        self.assertIn(
            f"Half-to-half gap: system_a {s['gap']['system_a']:.1%}, "
            f"system_b {s['gap']['system_b']:.1%}, "
            f"B − A difference "
            f"{s['gap']['accuracy_difference_b_minus_a']:.1%}.", report)
        verdict = "balanced" if s["balanced"] else "unbalanced"
        self.assertIn(f"**{verdict}", report)

    def test_report_without_split_half_data_omits_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        del res["split_half"]
        self.assertNotIn("## Split-half reliability", render_report(res))

    def test_cli_writes_split_half_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            s = res["split_half"]
            self.assertEqual(s["halves"]["half_1"]["n"]
                             + s["halves"]["half_2"]["n"],
                             res["gold_size"])
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Split-half reliability", f.read())


if __name__ == "__main__":
    unittest.main()
