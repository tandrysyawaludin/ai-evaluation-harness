"""Failures export: one CSV row per failed question, for manual review."""
import csv
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
from evalharness.failures import (FAILURE_COLUMNS, failure_rows,
                                  write_failures_csv)
from evalharness.run_eval import render_report, run


def _record(qid, error=None, category="count_total", difficulty="easy",
            candidate_sql="SELECT 1", gold_sql="SELECT 2",
            exact_match=False, latency_ms=0.5):
    return {
        "id": qid, "category": category, "difficulty": difficulty,
        "candidate_sql": candidate_sql, "gold_sql": gold_sql,
        "execution_correct": error is None,
        "exact_match": exact_match, "error": error,
        "latency_ms": latency_ms,
    }


def _fake_result():
    return {
        "systems": {
            # system_a: one failure, one pass, one failure with SQL
            # containing commas and quotes (CSV quoting must survive).
            "system_a": {"records": [
                _record("q002", error="wrong_filter"),
                _record("q001"),
                _record("q003", error="execution_error",
                        candidate_sql="SELECT COUNT(*) FROM orders WHERE "
                        "side = 'buy', status = \"open\""),
            ]},
            # system_b: one failure on a question system_a passed.
            "system_b": {"records": [
                _record("q001", error="empty_result"),
                _record("q002"),
            ]},
        }
    }


_GOLD = [
    {"id": "q001", "question": "How many orders?"},
    {"id": "q002", "question": "How many clients?"},
    {"id": "q003", "question": "How many accounts?"},
]


class TestFailureRows(unittest.TestCase):
    def test_only_failures_included_sorted_by_system_then_id(self):
        rows = failure_rows(_fake_result(), gold=_GOLD)
        self.assertEqual(
            [(r["system"], r["id"]) for r in rows],
            [("system_a", "q002"), ("system_a", "q003"),
             ("system_b", "q001")])

    def test_columns_and_question_text_joined(self):
        rows = failure_rows(_fake_result(), gold=_GOLD)
        self.assertEqual(set(rows[0]), set(FAILURE_COLUMNS))
        row = next(r for r in rows if r["id"] == "q002")
        self.assertEqual(row["question"], "How many clients?")
        self.assertEqual(row["category"], "count_total")
        self.assertEqual(row["difficulty"], "easy")
        self.assertEqual(row["error"], "wrong_filter")
        self.assertEqual(row["candidate_sql"], "SELECT 1")
        self.assertEqual(row["gold_sql"], "SELECT 2")
        self.assertFalse(row["exact_match"])
        self.assertEqual(row["latency_ms"], 0.5)

    def test_missing_gold_leaves_question_empty(self):
        rows = failure_rows(_fake_result())
        self.assertTrue(all(r["question"] == "" for r in rows))

    def test_gold_without_matching_id_leaves_question_empty(self):
        rows = failure_rows(_fake_result(),
                            gold=[{"id": "q999", "question": "Other"}])
        self.assertTrue(all(r["question"] == "" for r in rows))


class TestWriteFailuresCsv(unittest.TestCase):
    def _read_back(self, result, gold=_GOLD):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False) as tmp:
            path = tmp.name
        try:
            n = write_failures_csv(result, path, gold=gold)
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            with open(path, newline="") as f:
                header = f.readline().strip()
            return n, rows, header
        finally:
            os.unlink(path)

    def test_round_trip_with_quoting(self):
        n, rows, header = self._read_back(_fake_result())
        self.assertEqual(n, 3)
        self.assertEqual(header, ",".join(FAILURE_COLUMNS))
        # SQL with commas and quotes survives the CSV round trip intact.
        tricky = next(r for r in rows if r["id"] == "q003")
        self.assertEqual(
            tricky["candidate_sql"],
            "SELECT COUNT(*) FROM orders WHERE side = 'buy', status = \"open\"")
        self.assertEqual(tricky["system"], "system_a")
        self.assertEqual(tricky["error"], "execution_error")

    def test_no_failures_writes_header_only(self):
        result = {"systems": {"system_a": {"records": [_record("q001")]},
                              "system_b": {"records": [_record("q002")]}}}
        n, rows, header = self._read_back(result)
        self.assertEqual(n, 0)
        self.assertEqual(rows, [])
        self.assertEqual(header, ",".join(FAILURE_COLUMNS))


class TestCliAndReport(unittest.TestCase):
    def test_cli_writes_failures_csv_next_to_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            csv_path = os.path.join(tmp, "failures.csv")
            self.assertTrue(os.path.exists(csv_path))
            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))
            # system_a fails 36 of 65 (44.6% accuracy); system_b is perfect.
            self.assertEqual(len(rows), 36)
            self.assertTrue(all(r["system"] == "system_a" for r in rows))
            self.assertTrue(all(r["question"] for r in rows))
            self.assertTrue(all(r["error"] for r in rows))
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("failures.csv", f.read())

    def test_cli_failures_csv_flag_overrides_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = os.path.join(tmp, "review.csv")
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp, "--failures-csv", custom]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            self.assertTrue(os.path.exists(custom))
            self.assertFalse(os.path.exists(os.path.join(tmp, "failures.csv")))

    def test_report_without_failures_arg_has_no_line(self):
        res = run(runs=1, seed=42)
        self.assertNotIn("failures.csv", render_report(res))
        report = render_report(res, failures_csv="results/failures.csv")
        self.assertIn("Full failure list for manual error review: "
                      "`results/failures.csv`", report)


if __name__ == "__main__":
    unittest.main()
