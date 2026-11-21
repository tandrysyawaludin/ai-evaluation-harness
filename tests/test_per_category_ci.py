"""Per-category Wilson 95% CIs in the per-category accuracy table."""
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
from evalharness.stats import wilson_interval


def _item(i, category):
    return {"id": f"q{i}", "category": category}


def _rec(i, correct):
    return {"id": f"q{i}", "execution_correct": correct}


class TestBuildPerCategory(unittest.TestCase):
    def test_accuracies_and_correct_counts(self):
        gold = [_item(0, "alpha"), _item(1, "alpha"), _item(2, "beta"),
                _item(3, "beta"), _item(4, "beta")]
        ra = [_rec(0, True), _rec(1, False), _rec(2, True),
              _rec(3, True), _rec(4, True)]
        rb = [_rec(0, True), _rec(1, True), _rec(2, True),
              _rec(3, True), _rec(4, False)]
        cats = build_per_category(gold, ra, rb)
        self.assertEqual(cats["alpha"]["n"], 2)
        self.assertEqual(cats["alpha"]["system_a_correct"], 1)
        self.assertEqual(cats["alpha"]["system_b_correct"], 2)
        self.assertEqual(cats["alpha"]["system_a_accuracy"], 0.5)
        self.assertEqual(cats["alpha"]["system_b_accuracy"], 1.0)
        self.assertEqual(cats["beta"]["n"], 3)
        self.assertEqual(cats["beta"]["system_a_accuracy"], 1.0)
        self.assertAlmostEqual(cats["beta"]["system_b_accuracy"], 2 / 3)

    def test_ci_matches_wilson_interval(self):
        # 3 of 4 right in one category, 0 of 2 in another: the CI must
        # be exactly stats.wilson_interval on the same counts, so the
        # table and the accuracy can never disagree.
        gold = [_item(i, "a" if i < 4 else "b") for i in range(6)]
        ra = [_rec(i, i < 3) for i in range(6)]
        rb = [_rec(i, True) for i in range(6)]
        cats = build_per_category(gold, ra, rb)
        self.assertEqual(cats["a"]["system_a_wilson_95ci"],
                         wilson_interval(3, 4))
        self.assertEqual(cats["a"]["system_b_wilson_95ci"],
                         wilson_interval(4, 4))
        self.assertEqual(cats["b"]["system_a_wilson_95ci"],
                         wilson_interval(0, 2))
        self.assertEqual(cats["b"]["system_b_wilson_95ci"],
                         wilson_interval(2, 2))

    def test_ci_contains_accuracy_and_stays_in_unit_interval(self):
        gold = [_item(i, "a" if i < 4 else "b") for i in range(6)]
        ra = [_rec(i, i < 3) for i in range(6)]
        rb = [_rec(i, True) for i in range(6)]
        for cat, v in build_per_category(gold, ra, rb).items():
            for name in ("system_a", "system_b"):
                lo, hi = v[f"{name}_wilson_95ci"]
                self.assertGreaterEqual(lo, 0.0)
                self.assertLessEqual(hi, 1.0)
                self.assertLessEqual(lo, v[f"{name}_accuracy"])
                self.assertGreaterEqual(hi, v[f"{name}_accuracy"])

    def test_small_n_means_wide_ci(self):
        # The whole point: 1/1 and 10/10 are both 100%, but only the
        # second says anything. A single-question category's interval
        # must be far wider than a ten-question one's.
        gold = [_item(0, "tiny")] + [_item(i, "big") for i in range(1, 11)]
        ra = [_rec(i, True) for i in range(11)]
        rb = [_rec(i, True) for i in range(11)]
        cats = build_per_category(gold, ra, rb)
        tiny_lo, tiny_hi = cats["tiny"]["system_a_wilson_95ci"]
        big_lo, big_hi = cats["big"]["system_a_wilson_95ci"]
        self.assertEqual(cats["tiny"]["system_a_accuracy"], 1.0)
        self.assertEqual(cats["big"]["system_a_accuracy"], 1.0)
        self.assertGreater(tiny_hi - tiny_lo, big_hi - big_lo)
        self.assertAlmostEqual(tiny_lo, 0.207, places=3)
        self.assertAlmostEqual(big_lo, 0.722, places=3)

    def test_categories_sorted_alphabetically(self):
        gold = [_item(0, "zeta"), _item(1, "alpha"), _item(2, "mid")]
        ra = [_rec(i, True) for i in range(3)]
        rb = [_rec(i, True) for i in range(3)]
        self.assertEqual(list(build_per_category(gold, ra, rb)),
                         ["alpha", "mid", "zeta"])

    def test_misaligned_records_raise(self):
        gold = [_item(0, "a"), _item(1, "a")]
        ra = [_rec(0, True), _rec(1, True)]
        rb = [_rec(0, True)]
        with self.assertRaises(ValueError):
            build_per_category(gold, ra, rb)
        rb_bad = [_rec(0, True), _rec(9, True)]
        with self.assertRaises(ValueError):
            build_per_category(gold, ra, rb_bad)


class TestRunPerCategoryCI(unittest.TestCase):
    def test_run_carries_per_category_cis(self):
        res = run(runs=1, seed=42)
        cats = res["per_category"]
        # count_by_date_range: system_a 0/10, system_b 10/10.
        d = cats["count_by_date_range"]
        self.assertEqual(d["n"], 10)
        self.assertEqual(d["system_a_correct"], 0)
        self.assertEqual(d["system_b_correct"], 10)
        self.assertEqual([round(x, 3) for x in d["system_a_wilson_95ci"]],
                         [0.0, 0.278])
        self.assertEqual([round(x, 3) for x in d["system_b_wilson_95ci"]],
                         [0.722, 1.0])
        # Every category carries both CIs, and each CI contains its
        # accuracy — including the single-question categories, whose
        # intervals must be wide ([0.207, 1.0] at 1/1).
        for cat, v in cats.items():
            for name in ("system_a", "system_b"):
                lo, hi = v[f"{name}_wilson_95ci"]
                self.assertLessEqual(lo, v[f"{name}_accuracy"])
                self.assertGreaterEqual(hi, v[f"{name}_accuracy"])
        self.assertEqual([round(x, 3) for x in
                          cats["avg_quantity"]["system_a_wilson_95ci"]],
                         [0.207, 1.0])

    def test_report_renders_ci_columns(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Per-category accuracy", report)
        self.assertIn("| Category | n | system_a | system_a 95% Wilson CI "
                      "| system_b | system_b 95% Wilson CI |", report)
        self.assertIn("| count_by_date_range | 10 | 0% | [0.000, 0.278] "
                      "| 100% | [0.722, 1.000] |", report)
        self.assertIn("| avg_quantity | 1 | 100% | [0.207, 1.000] "
                      "| 100% | [0.207, 1.000] |", report)

    def test_report_without_ci_data_renders_dash(self):
        # Results files written before this feature have no CI keys.
        res = run(runs=1, seed=42)
        for v in res["per_category"].values():
            v.pop("system_a_wilson_95ci", None)
            v.pop("system_b_wilson_95ci", None)
        report = render_report(res)
        self.assertIn("| count_by_date_range | 10 | 0% | — "
                      "| 100% | — |", report)

    def test_cli_writes_cis_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            d = res["per_category"]["count_by_date_range"]
            # Tuples serialise as JSON lists; the values survive.
            self.assertEqual([round(x, 3) for x in
                              d["system_a_wilson_95ci"]], [0.0, 0.278])
            self.assertEqual([round(x, 3) for x in
                              d["system_b_wilson_95ci"]], [0.722, 1.0])
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("system_a 95% Wilson CI", report)
            self.assertIn("| count_by_date_range | 10 | 0% | [0.000, 0.278] "
                          "| 100% | [0.722, 1.000] |", report)


if __name__ == "__main__":
    unittest.main()
