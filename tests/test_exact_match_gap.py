"""Exact-match gap per category: execution-correct but SQL differs."""
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
from evalharness.run_eval import build_per_category, render_report, run


def _item(i, category):
    return {"id": f"q{i}", "category": category}


def _rec(i, correct, exact):
    return {"id": f"q{i}", "execution_correct": correct,
            "exact_match": exact}


class TestBuildPerCategoryExactMatchGap(unittest.TestCase):
    def test_gap_counts_correct_but_not_exact(self):
        # Category "a": A right on 3, exact on 1 (gap 2); B right on 2,
        # exact on 2 (gap 0). Category "b": A right on 0 (gap 0);
        # B right on 1, exact on 0 (gap 1).
        gold = [_item(i, "a" if i < 4 else "b") for i in range(6)]
        ra = [_rec(0, True, True), _rec(1, True, False),
              _rec(2, True, False), _rec(3, False, False),
              _rec(4, False, False), _rec(5, False, False)]
        rb = [_rec(0, True, True), _rec(1, True, True),
              _rec(2, False, False), _rec(3, False, False),
              _rec(4, True, False), _rec(5, False, False)]
        cats = build_per_category(gold, ra, rb)
        a = cats["a"]
        self.assertEqual(a["system_a_correct"], 3)
        self.assertEqual(a["system_a_exact_match"], 1)
        self.assertEqual(a["system_a_exact_match_gap"], 2)
        self.assertAlmostEqual(a["system_a_exact_match_rate"], 0.25)
        self.assertAlmostEqual(a["system_a_exact_match_gap_rate"], 0.5)
        self.assertEqual(a["system_b_exact_match_gap"], 0)
        self.assertAlmostEqual(a["system_b_exact_match_gap_rate"], 0.0)
        b = cats["b"]
        self.assertEqual(b["system_a_exact_match_gap"], 0)
        self.assertEqual(b["system_b_correct"], 1)
        self.assertEqual(b["system_b_exact_match"], 0)
        self.assertEqual(b["system_b_exact_match_gap"], 1)
        self.assertAlmostEqual(b["system_b_exact_match_gap_rate"], 0.5)

    def test_gap_rate_is_accuracy_minus_exact_rate(self):
        # The gap rate must equal execution accuracy minus exact-match
        # rate, so the three numbers in a row can never disagree.
        gold = [_item(i, "a" if i < 5 else "b") for i in range(8)]
        ra = [_rec(i, i % 2 == 0, i % 4 == 0) for i in range(8)]
        rb = [_rec(i, i % 3 == 0, i % 6 == 0) for i in range(8)]
        for v in build_per_category(gold, ra, rb).values():
            for name in ("system_a", "system_b"):
                self.assertAlmostEqual(
                    v[f"{name}_exact_match_gap_rate"],
                    v[f"{name}_accuracy"] - v[f"{name}_exact_match_rate"])
                self.assertEqual(
                    v[f"{name}_exact_match_gap"],
                    v[f"{name}_correct"] - v[f"{name}_exact_match"])

    def test_zero_gap_when_exact_equals_correct(self):
        gold = [_item(i, "same") for i in range(4)]
        ra = [_rec(i, True, True) for i in range(4)]
        rb = [_rec(i, False, False) for i in range(4)]
        v = build_per_category(gold, ra, rb)["same"]
        self.assertEqual(v["system_a_exact_match_gap"], 0)
        self.assertEqual(v["system_b_exact_match_gap"], 0)


class TestRunExactMatchGap(unittest.TestCase):
    def test_run_carries_gap_per_category(self):
        res = run(runs=1, seed=42)
        cats = res["per_category"]
        # system_b is right on all 10 date-range questions but writes
        # the 5 month questions with strftime instead of BETWEEN.
        d = cats["count_by_date_range"]
        self.assertEqual(d["system_b_correct"], 10)
        self.assertEqual(d["system_b_exact_match"], 5)
        self.assertEqual(d["system_b_exact_match_gap"], 5)
        self.assertAlmostEqual(d["system_b_exact_match_gap_rate"], 0.5)
        self.assertEqual(d["system_a_exact_match_gap"], 0)
        # The gap lives in exactly one category.
        gap_cats = [c for c, v in cats.items()
                    if v["system_b_exact_match_gap"]]
        self.assertEqual(gap_cats, ["count_by_date_range"])
        self.assertEqual(sum(v["system_b_exact_match_gap"]
                             for v in cats.values()), 5)
        self.assertEqual(sum(v["system_a_exact_match_gap"]
                             for v in cats.values()), 0)

    def test_report_renders_gap_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Exact-match gap by category", report)
        self.assertIn("| Category | n | system_a exec | system_a exact "
                      "| system_a gap | system_b exec | system_b exact "
                      "| system_b gap |", report)
        self.assertIn("| count_by_date_range | 10 | 0 (0%) | 0 (0%) | "
                      "0 (0%) | 10 (100%) | 5 (50%) | 5 (50%) |", report)
        self.assertIn("| count_by_account | 5 | 5 (100%) | 5 (100%) | "
                      "0 (0%) | 5 (100%) | 5 (100%) | 0 (0%) |", report)
        self.assertIn("Overall gap: system_a 0 of 65 (0%), "
                      "system_b 5 of 65 (8%).", report)
        self.assertIn("The gap is concentrated: 5 of system_b's 5 gap "
                      "questions sit in count_by_date_range — its month "
                      "questions are written with "
                      "`strftime('%Y-%m', order_date)` where the gold SQL "
                      "uses `BETWEEN`, the same filter in another form.",
                      report)

    def test_report_without_gap_data_renders_dash(self):
        # Results files written before this feature have no gap keys.
        res = run(runs=1, seed=42)
        for v in res["per_category"].values():
            for key in list(v):
                if "exact_match" in key:
                    v.pop(key)
        report = render_report(res)
        self.assertIn("## Exact-match gap by category", report)
        self.assertIn("| count_by_date_range | 10 | 0 (0%) | — | — | "
                      "10 (100%) | — | — |", report)
        self.assertNotIn("Overall gap:", report)

    def test_cli_writes_gap_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            d = res["per_category"]["count_by_date_range"]
            self.assertEqual(d["system_b_exact_match_gap"], 5)
            self.assertAlmostEqual(d["system_b_exact_match_gap_rate"], 0.5)
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("## Exact-match gap by category", report)
            self.assertIn("| count_by_date_range | 10 | 0 (0%) | 0 (0%) | "
                          "0 (0%) | 10 (100%) | 5 (50%) | 5 (50%) |",
                          report)


if __name__ == "__main__":
    unittest.main()
