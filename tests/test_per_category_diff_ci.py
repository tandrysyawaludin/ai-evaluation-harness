"""Per-category paired bootstrap CI for the B - A accuracy difference."""
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
from evalharness.stats import bootstrap_diff_ci


def _item(i, category):
    return {"id": f"q{i}", "category": category}


def _rec(i, correct):
    return {"id": f"q{i}", "execution_correct": correct}


class TestBuildPerCategoryDiffCI(unittest.TestCase):
    def test_difference_and_ci_match_bootstrap(self):
        # Categories sort alphabetically, so "a" gets seed 123 and
        # "b" seed 124; the CI must be exactly stats.bootstrap_diff_ci
        # on the same paired flags, so the table and the paired
        # difference can never disagree.
        gold = [_item(i, "a" if i < 4 else "b") for i in range(6)]
        ra = [_rec(0, True), _rec(1, False), _rec(2, True), _rec(3, False),
              _rec(4, True), _rec(5, True)]
        rb = [_rec(0, True), _rec(1, True), _rec(2, False), _rec(3, False),
              _rec(4, False), _rec(5, True)]
        cats = build_per_category(gold, ra, rb)
        self.assertEqual(cats["a"]["difference_b_minus_a"], 0.0)
        self.assertEqual(cats["a"]["difference_bootstrap_95ci"],
                         bootstrap_diff_ci([1, 0, 1, 0], [1, 1, 0, 0],
                                           seed=123))
        self.assertAlmostEqual(cats["b"]["difference_b_minus_a"], -0.5)
        self.assertEqual(cats["b"]["difference_bootstrap_95ci"],
                         bootstrap_diff_ci([1, 1], [0, 1], seed=124))

    def test_ci_contains_difference(self):
        gold = [_item(i, "a" if i < 5 else "b") for i in range(8)]
        ra = [_rec(i, i % 2 == 0) for i in range(8)]
        rb = [_rec(i, i % 3 == 0) for i in range(8)]
        for cat, v in build_per_category(gold, ra, rb).items():
            lo, hi = v["difference_bootstrap_95ci"]
            self.assertLessEqual(lo, v["difference_b_minus_a"])
            self.assertGreaterEqual(hi, v["difference_b_minus_a"])
            self.assertLessEqual(lo, 1.0)
            self.assertGreaterEqual(hi, -1.0)

    def test_unanimous_category_has_degenerate_ci(self):
        # B wins every question: the difference is +1 on every
        # resample, so the interval collapses to [1, 1]. The mirror
        # case — both systems agree everywhere — collapses to [0, 0].
        gold = [_item(i, "sweep") for i in range(4)] + \
               [_item(i + 4, "tie") for i in range(4)]
        ra = [_rec(i, False) for i in range(4)] + \
             [_rec(i + 4, True) for i in range(4)]
        rb = [_rec(i, True) for i in range(8)]
        cats = build_per_category(gold, ra, rb)
        self.assertEqual(cats["sweep"]["difference_b_minus_a"], 1.0)
        self.assertEqual(cats["sweep"]["difference_bootstrap_95ci"],
                         (1.0, 1.0))
        self.assertEqual(cats["tie"]["difference_b_minus_a"], 0.0)
        self.assertEqual(cats["tie"]["difference_bootstrap_95ci"],
                         (0.0, 0.0))

    def test_paired_ci_narrower_than_wilson_gap_suggests(self):
        # Both systems right on 9 of 10 questions, B alone right on
        # the tenth: the paired difference is +0.1 and the paired CI
        # stays tight, while the two Wilson intervals (each roughly
        # [0.60, 1.00] at 9/10 vs [0.72, 1.00] at 10/10) overlap
        # almost completely and would say nothing. That is the whole
        # point of pairing: the shared questions cancel out.
        gold = [_item(i, "paired") for i in range(10)]
        ra = [_rec(i, i < 9) for i in range(10)]
        rb = [_rec(i, True) for i in range(10)]
        v = build_per_category(gold, ra, rb)["paired"]
        self.assertEqual(v["difference_b_minus_a"], 0.1)
        lo, hi = v["difference_bootstrap_95ci"]
        self.assertLess(hi - lo, 0.5)
        a_lo, a_hi = v["system_a_wilson_95ci"]
        self.assertGreater(a_hi - a_lo, hi - lo)

    def test_deterministic_across_calls(self):
        gold = [_item(i, "a" if i < 4 else "b") for i in range(6)]
        ra = [_rec(i, i % 2 == 0) for i in range(6)]
        rb = [_rec(i, i % 3 == 0) for i in range(6)]
        first = build_per_category(gold, ra, rb)
        second = build_per_category(gold, ra, rb)
        self.assertEqual(first, second)


class TestRunPerCategoryDiffCI(unittest.TestCase):
    def test_run_carries_per_category_diff_cis(self):
        res = run(runs=1, seed=42)
        cats = res["per_category"]
        # count_by_date_range: system_a 0/10, system_b 10/10.
        d = cats["count_by_date_range"]
        self.assertEqual(d["difference_b_minus_a"], 1.0)
        self.assertEqual([round(x, 3) for x in
                          d["difference_bootstrap_95ci"]], [1.0, 1.0])
        # Every category carries the difference and its CI, and each
        # CI contains its difference.
        for cat, v in cats.items():
            lo, hi = v["difference_bootstrap_95ci"]
            self.assertLessEqual(lo, v["difference_b_minus_a"])
            self.assertGreaterEqual(hi, v["difference_b_minus_a"])
        # Single-question category where both agree: 0 difference,
        # degenerate interval.
        self.assertEqual(cats["avg_quantity"]["difference_b_minus_a"], 0.0)
        self.assertEqual(cats["avg_quantity"]["difference_bootstrap_95ci"],
                         (0.0, 0.0))

    def test_report_renders_diff_columns(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Per-category accuracy", report)
        self.assertIn("| Category | n | system_a | system_a 95% Wilson CI "
                      "| system_b | system_b 95% Wilson CI | B − A | "
                      "B − A 95% bootstrap CI |", report)
        self.assertIn("| count_by_date_range | 10 | 0% | [0.000, 0.278] "
                      "| 100% | [0.722, 1.000] | +100% | [1.000, 1.000] |",
                      report)
        self.assertIn("| avg_quantity | 1 | 100% | [0.207, 1.000] "
                      "| 100% | [0.207, 1.000] | +0% | [0.000, 0.000] |",
                      report)

    def test_report_without_diff_data_renders_dash(self):
        # Results files written before this feature have no diff keys.
        res = run(runs=1, seed=42)
        for v in res["per_category"].values():
            v.pop("difference_b_minus_a", None)
            v.pop("difference_bootstrap_95ci", None)
        report = render_report(res)
        self.assertIn("| count_by_date_range | 10 | 0% | [0.000, 0.278] "
                      "| 100% | [0.722, 1.000] | — | — |", report)

    def test_cli_writes_diff_cis_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            d = res["per_category"]["count_by_date_range"]
            self.assertEqual(d["difference_b_minus_a"], 1.0)
            # Tuples serialise as JSON lists; the values survive.
            self.assertEqual([round(x, 3) for x in
                              d["difference_bootstrap_95ci"]], [1.0, 1.0])
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("B − A 95% bootstrap CI", report)
            self.assertIn("| count_by_date_range | 10 | 0% | [0.000, 0.278] "
                          "| 100% | [0.722, 1.000] | +100% | [1.000, 1.000] |",
                          report)


if __name__ == "__main__":
    unittest.main()
