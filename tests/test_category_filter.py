"""--category filter: run the eval on a subset of gold categories."""
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
from evalharness.run_eval import (filter_gold_by_category, load_jsonl,
                                  render_report, run)

GOLD_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "gold.jsonl")


class TestFilterGoldByCategory(unittest.TestCase):
    def test_single_category_keeps_only_that_category(self):
        gold = load_jsonl(GOLD_PATH)
        filtered = filter_gold_by_category(gold, ["count_by_date_range"])
        self.assertEqual(len(filtered), 10)
        self.assertTrue(all(r["category"] == "count_by_date_range"
                            for r in filtered))
        # Order is preserved: the filtered list is a subsequence.
        self.assertEqual([r["id"] for r in filtered],
                         [r["id"] for r in gold
                          if r["category"] == "count_by_date_range"])

    def test_multiple_categories_union(self):
        gold = load_jsonl(GOLD_PATH)
        filtered = filter_gold_by_category(
            gold, ["top_symbol_by_volume", "max_quantity"])
        self.assertEqual(len(filtered), 2)
        self.assertEqual({r["category"] for r in filtered},
                         {"top_symbol_by_volume", "max_quantity"})

    def test_no_filter_returns_the_same_list(self):
        gold = load_jsonl(GOLD_PATH)
        self.assertIs(filter_gold_by_category(gold, None), gold)
        self.assertIs(filter_gold_by_category(gold, []), gold)

    def test_unknown_category_fails_with_available_list(self):
        gold = load_jsonl(GOLD_PATH)
        with self.assertRaises(ValueError) as ctx:
            filter_gold_by_category(gold, ["count_by_date_range", "nope"])
        msg = str(ctx.exception)
        self.assertIn("unknown category: nope", msg)
        self.assertIn("Available categories:", msg)
        self.assertIn("count_by_date_range", msg)

    def test_unknown_categories_plural(self):
        gold = load_jsonl(GOLD_PATH)
        with self.assertRaises(ValueError) as ctx:
            filter_gold_by_category(gold, ["nope", "alsono"])
        self.assertIn("unknown categories: alsono, nope", str(ctx.exception))


class TestRunWithCategoryFilter(unittest.TestCase):
    def test_filtered_run_records_filter_and_full_size(self):
        res = run(runs=1, seed=42, categories=["count_by_date_range"])
        self.assertEqual(res["gold_size"], 10)
        self.assertEqual(res["gold_total"], 65)
        self.assertEqual(res["category_filter"], ["count_by_date_range"])
        self.assertEqual(list(res["per_category"]), ["count_by_date_range"])
        self.assertEqual(res["systems"]["system_a"]["n"], 10)
        self.assertEqual(res["systems"]["system_b"]["n"], 10)
        self.assertEqual(
            {r["category"] for r in res["systems"]["system_a"]["records"]},
            {"count_by_date_range"})

    def test_multiple_categories_sorted_in_result(self):
        res = run(runs=1, seed=42,
                  categories=["sum_value_by_symbol", "count_total"])
        self.assertEqual(res["gold_size"], 9)
        self.assertEqual(res["category_filter"],
                         ["count_total", "sum_value_by_symbol"])

    def test_unfiltered_run_records_no_filter(self):
        res = run(runs=1, seed=42)
        self.assertEqual(res["gold_size"], 65)
        self.assertEqual(res["gold_total"], 65)
        self.assertIsNone(res["category_filter"])

    def test_unknown_category_raises(self):
        with self.assertRaises(ValueError) as ctx:
            run(runs=1, seed=42, categories=["not_a_category"])
        self.assertIn("unknown category: not_a_category", str(ctx.exception))

    def test_report_marks_filtered_run(self):
        res = run(runs=1, seed=42, categories=["count_by_date_range"])
        report = render_report(res)
        self.assertIn("Filtered to 1 category (count_by_date_range): "
                      "10 of 65 gold questions.", report)
        self.assertIn("compare them against a run on the same subset",
                      report)

    def test_report_marks_unfiltered_run_as_full(self):
        res = run(runs=1, seed=42)
        self.assertNotIn("Filtered to", render_report(res))


class TestCategoryCli(unittest.TestCase):
    def test_cli_writes_filter_to_results_json_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--category", "count_by_date_range", "avg_price_by_symbol",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            self.assertEqual(res["gold_size"], 15)
            self.assertEqual(res["gold_total"], 65)
            self.assertEqual(res["category_filter"],
                             ["avg_price_by_symbol", "count_by_date_range"])
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("Filtered to 2 categories "
                          "(avg_price_by_symbol, count_by_date_range): "
                          "15 of 65 gold questions.", report)

    def test_cli_unknown_category_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--category", "not_a_category", "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(ValueError):
                    with redirect_stdout(io.StringIO()):
                        run_eval.main()


if __name__ == "__main__":
    unittest.main()
