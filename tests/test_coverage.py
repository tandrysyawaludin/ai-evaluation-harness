"""Gold-set coverage matrix: category x difficulty counts in the report."""
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
from evalharness.run_eval import build_coverage_matrix, render_report, run


def _gold(qid, category="count_total", difficulty="easy"):
    return {"id": qid, "category": category, "difficulty": difficulty}


class TestBuildCoverageMatrix(unittest.TestCase):
    def test_counts_per_cell(self):
        gold = [_gold("q1", "count_total", "easy"),
                _gold("q2", "count_total", "easy"),
                _gold("q3", "count_total", "hard"),
                _gold("q4", "sum_value", "medium")]
        m = build_coverage_matrix(gold)
        self.assertEqual(m["categories"], ["count_total", "sum_value"])
        self.assertEqual(m["difficulties"], ["easy", "medium", "hard"])
        self.assertEqual(m["cells"]["count_total"],
                         {"easy": 2, "medium": 0, "hard": 1})
        self.assertEqual(m["cells"]["sum_value"],
                         {"easy": 0, "medium": 1, "hard": 0})
        self.assertEqual(m["total_cells"], 6)
        self.assertEqual(m["thin_threshold"], 3)

    def test_empty_and_thin_cells_flagged(self):
        gold = [_gold("q1", "count_total", "easy"),
                _gold("q2", "count_total", "easy"),
                _gold("q3", "count_total", "easy"),
                _gold("q4", "count_total", "hard"),
                _gold("q5", "sum_value", "medium"),
                _gold("q6", "sum_value", "medium")]
        m = build_coverage_matrix(gold)
        # count_total/medium is empty; count_total/hard has 1, thin;
        # sum_value/medium has 2, thin; count_total/easy has 3, fine.
        self.assertEqual(
            [(c["category"], c["difficulty"]) for c in m["empty_cells"]],
            [("count_total", "medium"), ("sum_value", "easy"),
             ("sum_value", "hard")])
        self.assertEqual(
            [(c["category"], c["difficulty"], c["count"])
             for c in m["thin_cells"]],
            [("count_total", "hard", 1), ("sum_value", "medium", 2)])

    def test_custom_thin_threshold(self):
        gold = [_gold("q1", "count_total", "easy"),
                _gold("q2", "count_total", "easy")]
        m = build_coverage_matrix(gold, thin_threshold=2)
        self.assertEqual(m["thin_cells"], [])
        self.assertEqual(m["empty_cells"], [])

    def test_difficulties_ordered_easy_medium_hard(self):
        gold = [_gold("q1", "c", "hard"),
                _gold("q2", "c", "easy"),
                _gold("q3", "c", "medium")]
        m = build_coverage_matrix(gold)
        self.assertEqual(m["difficulties"], ["easy", "medium", "hard"])

    def test_unknown_difficulty_sorts_last(self):
        gold = [_gold("q1", "c", "hard"), _gold("q2", "c", "expert")]
        m = build_coverage_matrix(gold)
        self.assertEqual(m["difficulties"], ["hard", "expert"])

    def test_empty_input(self):
        m = build_coverage_matrix([])
        self.assertEqual(m["categories"], [])
        self.assertEqual(m["difficulties"], [])
        self.assertEqual(m["cells"], {})
        self.assertEqual(m["total_cells"], 0)
        self.assertEqual(m["empty_cells"], [])
        self.assertEqual(m["thin_cells"], [])


class TestRunCoverageMatrix(unittest.TestCase):
    def test_run_carries_coverage_matrix(self):
        res = run(runs=1, seed=42)
        m = res["coverage_matrix"]
        self.assertEqual(m["thin_threshold"], 3)
        self.assertEqual(m["total_cells"],
                         len(m["categories"]) * len(m["difficulties"]))
        self.assertEqual(sum(sum(row.values()) for row in m["cells"].values()),
                         res["gold_size"])
        # Every cell counted in the matrix is either empty, thin, or
        # at/above the threshold — no cell is silently dropped.
        for cat in m["categories"]:
            for diff in m["difficulties"]:
                n = m["cells"][cat][diff]
                in_empty = any(c["category"] == cat and
                               c["difficulty"] == diff for c in m["empty_cells"])
                in_thin = any(c["category"] == cat and
                              c["difficulty"] == diff for c in m["thin_cells"])
                self.assertEqual(in_empty, n == 0)
                self.assertEqual(in_thin, 0 < n < 3)

    def test_real_gold_set_has_empty_and_thin_cells(self):
        # The actual gold set is deliberately uneven: most categories
        # test a single difficulty, so the matrix must surface that.
        res = run(runs=1, seed=42)
        m = res["coverage_matrix"]
        self.assertGreater(len(m["empty_cells"]), 0)
        self.assertGreater(len(m["thin_cells"]), 0)

    def test_report_renders_coverage_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Gold-set coverage matrix", report)
        m = res["coverage_matrix"]
        n_empty = len(m["empty_cells"])
        n_thin = len(m["thin_cells"])
        self.assertIn(
            f"Coverage: {m['total_cells'] - n_empty - n_thin} of "
            f"{m['total_cells']} cells have at least 3 questions, "
            f"{n_thin} thin, {n_empty} empty.", report)
        self.assertIn("Empty cells:", report)
        self.assertIn("Thin cells:", report)
        # A known thin cell from the real gold set: top_symbol_by_volume
        # has a single hard question.
        self.assertIn("top_symbol_by_volume / hard (1)", report)

    def test_report_without_coverage_data_omits_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        del res["coverage_matrix"]
        self.assertNotIn("## Gold-set coverage matrix", render_report(res))

    def test_cli_writes_coverage_matrix_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            m = res["coverage_matrix"]
            self.assertEqual(m["thin_threshold"], 3)
            self.assertEqual(sum(sum(r.values()) for r in m["cells"].values()),
                             res["gold_size"])
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Gold-set coverage matrix", f.read())


if __name__ == "__main__":
    unittest.main()
