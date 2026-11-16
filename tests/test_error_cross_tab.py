"""Error-type x category cross-tab: which error types cluster where."""
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
from evalharness.run_eval import (ERROR_TYPES, build_error_cross_tab,
                                  render_report, run)


def _rec(qid, category, error):
    return {"id": qid, "category": category,
            "execution_correct": error is None, "error": error}


def _pair(records):
    """Same records for both systems, so the cross-tab is per-system."""
    return build_error_cross_tab(records, list(records))


class TestBuildErrorCrossTab(unittest.TestCase):
    def test_counts_and_totals(self):
        records = [
            _rec("q1", "cat_a", "wrong_filter"),
            _rec("q2", "cat_a", "wrong_filter"),
            _rec("q3", "cat_a", "wrong_join"),
            _rec("q4", "cat_b", "wrong_filter"),
            _rec("q5", "cat_b", None),  # correct: no cell, no total
        ]
        ct = _pair(records)
        self.assertEqual(ct["categories"], ["cat_a", "cat_b"])
        self.assertEqual(ct["error_types"], list(ERROR_TYPES))
        tab = ct["systems"]["system_a"]
        self.assertEqual(tab["cells"]["cat_a"]["wrong_filter"], 2)
        self.assertEqual(tab["cells"]["cat_a"]["wrong_join"], 1)
        self.assertEqual(tab["cells"]["cat_b"]["wrong_filter"], 1)
        self.assertEqual(tab["cells"]["cat_b"]["wrong_join"], 0)
        self.assertEqual(tab["category_totals"], {"cat_a": 3, "cat_b": 1})
        self.assertEqual(tab["error_totals"]["wrong_filter"], 3)
        self.assertEqual(tab["error_totals"]["wrong_join"], 1)
        self.assertEqual(tab["total_errors"], 4)
        # Cells sum to the category totals and to the error totals.
        for cat in ct["categories"]:
            self.assertEqual(sum(tab["cells"][cat].values()),
                             tab["category_totals"][cat])
        for err in ERROR_TYPES:
            self.assertEqual(
                sum(tab["cells"][cat][err] for cat in ct["categories"]),
                tab["error_totals"][err])

    def test_every_error_type_is_a_column_even_when_zero(self):
        records = [_rec("q1", "cat_a", "wrong_filter")]
        tab = _pair(records)["systems"]["system_a"]
        for err in ERROR_TYPES:
            self.assertIn(err, tab["cells"]["cat_a"])
            self.assertIn(err, tab["error_totals"])
        self.assertEqual(tab["error_totals"]["no_sql_generated"], 0)
        self.assertEqual(tab["error_totals"]["wrong_result"], 0)

    def test_dominant_error_and_clean_category(self):
        records = [
            _rec("q1", "cat_a", "wrong_filter"),
            _rec("q2", "cat_a", "wrong_aggregation"),
            _rec("q3", "cat_a", "wrong_aggregation"),
            _rec("q4", "cat_b", None),  # clean category: no dominant error
        ]
        tab = _pair(records)["systems"]["system_a"]
        self.assertEqual(tab["dominant_error"]["cat_a"], "wrong_aggregation")
        self.assertIsNone(tab["dominant_error"]["cat_b"])

    def test_dominant_error_tie_breaks_in_error_type_order(self):
        # wrong_join and wrong_filter tie at 1 each; wrong_join comes
        # first in ERROR_TYPES, so it wins deterministically.
        records = [_rec("q1", "cat_a", "wrong_join"),
                   _rec("q2", "cat_a", "wrong_filter")]
        tab = _pair(records)["systems"]["system_a"]
        self.assertEqual(tab["dominant_error"]["cat_a"], "wrong_join")

    def test_systems_are_independent(self):
        a = [_rec("q1", "cat_a", "wrong_filter")]
        b = [_rec("q1", "cat_a", None)]
        ct = build_error_cross_tab(a, b)
        self.assertEqual(ct["systems"]["system_a"]["total_errors"], 1)
        self.assertEqual(ct["systems"]["system_b"]["total_errors"], 0)
        self.assertIsNone(
            ct["systems"]["system_b"]["dominant_error"]["cat_a"])

    def test_no_failures_at_all(self):
        records = [_rec("q1", "cat_a", None)]
        tab = _pair(records)["systems"]["system_a"]
        self.assertEqual(tab["total_errors"], 0)
        self.assertEqual(tab["error_totals"],
                         {err: 0 for err in ERROR_TYPES})
        self.assertIsNone(tab["dominant_error"]["cat_a"])

    def test_count_mismatch_raises(self):
        a = [_rec("q1", "cat_a", None)]
        b = [_rec("q1", "cat_a", None), _rec("q2", "cat_a", None)]
        with self.assertRaises(ValueError):
            build_error_cross_tab(a, b)

    def test_id_misalignment_raises(self):
        a = [_rec("q1", "cat_a", None), _rec("qX", "cat_a", None)]
        b = [_rec("q1", "cat_a", None), _rec("q2", "cat_a", None)]
        with self.assertRaises(ValueError):
            build_error_cross_tab(a, b)


class TestRunErrorCrossTab(unittest.TestCase):
    def test_run_carries_cross_tab_matching_error_counts(self):
        res = run(runs=1, seed=42)
        ct = res["error_cross_tab"]
        self.assertEqual(len(ct["categories"]), 20)
        for name in ("system_a", "system_b"):
            tab = ct["systems"][name]
            expected = res["systems"][name]["error_counts"]
            self.assertEqual(tab["total_errors"],
                             sum(expected.values()))
            for err, n in expected.items():
                self.assertEqual(tab["error_totals"][err], n)
            for err in ERROR_TYPES:
                self.assertEqual(tab["error_totals"][err],
                                 expected.get(err, 0))

    def test_real_gold_set_clustering(self):
        # system_a's known failure modes, verified against the real run:
        # date-range questions fail on filters, average-price questions
        # on aggregation, country counts on joins.
        res = run(runs=1, seed=42)
        tab = res["error_cross_tab"]["systems"]["system_a"]
        self.assertEqual(tab["total_errors"], 36)
        self.assertEqual(tab["cells"]["count_by_date_range"]
                         ["wrong_filter"], 10)
        self.assertEqual(tab["dominant_error"]["count_by_date_range"],
                         "wrong_filter")
        self.assertEqual(tab["cells"]["avg_price_by_symbol"]
                         ["wrong_aggregation"], 5)
        self.assertEqual(tab["dominant_error"]["avg_price_by_symbol"],
                         "wrong_aggregation")
        self.assertEqual(tab["cells"]["count_by_country"]["wrong_join"], 4)
        self.assertEqual(tab["dominant_error"]["count_by_country"],
                         "wrong_join")
        # system_b is error-free, so its cross-tab is all zeros.
        self.assertEqual(
            res["error_cross_tab"]["systems"]["system_b"]["total_errors"], 0)

    def test_report_renders_cross_tab_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Error-type × category cross-tab", report)
        ct = res["error_cross_tab"]
        tab = ct["systems"]["system_a"]
        # Header lists every error type; the date-range row shows the
        # dominant wrong_filter count bolded and the row total.
        self.assertIn("| Category | " + " | ".join(ct["error_types"])
                      + " | Total |", report)
        row = tab["cells"]["count_by_date_range"]
        cells = [f"**{row[e]}**" if e == "wrong_filter" else str(row[e])
                 for e in ct["error_types"]]
        self.assertIn("| count_by_date_range | " + " | ".join(cells)
                      + " | 10 |", report)
        self.assertIn("wrong_filter dominates 6 categories", report)
        self.assertIn("wrong_aggregation dominates 1 category", report)
        self.assertIn("wrong_join dominates 2 categories", report)
        # system_b has no failures, so it gets the no-failures line,
        # not an empty table.
        self.assertIn("- system_b: **0 failures**", report)

    def test_report_without_cross_tab_data_omits_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        del res["error_cross_tab"]
        self.assertNotIn("## Error-type × category cross-tab",
                         render_report(res))

    def test_cli_writes_cross_tab_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            self.assertEqual(
                res["error_cross_tab"]["systems"]["system_a"]
                ["total_errors"], 36)
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Error-type × category cross-tab",
                              f.read())


if __name__ == "__main__":
    unittest.main()
