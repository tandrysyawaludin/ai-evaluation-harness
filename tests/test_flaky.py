"""Flaky-question report: per-question pass-consistency across runs."""
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
from evalharness.run_eval import build_flaky_questions, render_report, run


def _gold(qid, category="count_total", difficulty="easy"):
    return {"id": qid, "category": category, "difficulty": difficulty}


class TestBuildFlakyQuestions(unittest.TestCase):
    def test_only_partially_correct_questions_listed(self):
        gold = [_gold("q1"), _gold("q2"), _gold("q3"), _gold("q4")]
        # q1 always right, q2 always wrong, q3 right 2/3, q4 right 1/3.
        flaky = build_flaky_questions(gold, [3, 0, 2, 1], runs=3)
        self.assertEqual(flaky["runs"], 3)
        self.assertEqual(flaky["flaky_count"], 2)
        self.assertEqual([q["id"] for q in flaky["questions"]],
                         ["q4", "q3"])  # least consistent first
        by_id = {q["id"]: q for q in flaky["questions"]}
        self.assertEqual(by_id["q3"]["correct_runs"], 2)
        self.assertAlmostEqual(by_id["q3"]["fraction_correct"], 2 / 3)
        self.assertEqual(by_id["q3"]["category"], "count_total")
        self.assertEqual(by_id["q3"]["difficulty"], "easy")

    def test_deterministic_system_has_no_flaky_questions(self):
        gold = [_gold("q1"), _gold("q2")]
        flaky = build_flaky_questions(gold, [3, 0], runs=3)
        self.assertEqual(flaky["flaky_count"], 0)
        self.assertEqual(flaky["questions"], [])

    def test_single_run_cannot_be_flaky(self):
        # With one repeated run a question is either right or wrong.
        gold = [_gold("q1"), _gold("q2")]
        flaky = build_flaky_questions(gold, [1, 0], runs=1)
        self.assertEqual(flaky["flaky_count"], 0)

    def test_mismatched_lengths_rejected(self):
        with self.assertRaises(ValueError):
            build_flaky_questions([_gold("q1")], [1, 0], runs=1)

    def test_zero_runs_rejected(self):
        with self.assertRaises(ValueError):
            build_flaky_questions([_gold("q1")], [0], runs=0)

    def test_empty_input(self):
        flaky = build_flaky_questions([], [], runs=3)
        self.assertEqual(flaky["flaky_count"], 0)
        self.assertEqual(flaky["questions"], [])


class TestRunFlakyQuestions(unittest.TestCase):
    def test_run_carries_flaky_report_for_both_systems(self):
        # The rule-based systems are deterministic: nothing is flaky,
        # and the report says so explicitly.
        res = run(runs=3, seed=42)
        for name in ("system_a", "system_b"):
            flaky = res["systems"][name]["flaky_questions"]
            self.assertEqual(flaky["runs"], 3)
            self.assertEqual(flaky["flaky_count"], 0)
            self.assertEqual(flaky["questions"], [])
            # Consistent with the aggregate pass-consistency numbers:
            # every question is right on all runs or wrong on all runs.
            self.assertAlmostEqual(
                res["systems"][name]["questions_correct_on_every_run"]
                + (res["systems"][name]["n"]
                   - res["systems"][name]["correct"]) / res["systems"][name]["n"],
                1.0)

    def test_report_renders_flaky_section_with_zero_counts(self):
        res = run(runs=3, seed=42)
        report = render_report(res)
        self.assertIn("## Flaky questions (pass-consistency across repeated runs)",
                      report)
        self.assertIn("system_a: **0 flaky questions**", report)
        self.assertIn("system_b: **0 flaky questions**", report)

    def test_report_renders_flaky_table_when_present(self):
        res = run(runs=1, seed=42)
        # Simulate a non-deterministic system by hand: q1 flaky 2/3.
        res["systems"]["system_a"]["flaky_questions"] = {
            "runs": 3, "flaky_count": 1,
            "questions": [{"id": "q001", "category": "count_total",
                           "difficulty": "easy", "correct_runs": 2,
                           "runs": 3, "fraction_correct": 2 / 3}]}
        res["systems"]["system_b"]["flaky_questions"] = {
            "runs": 3, "flaky_count": 0, "questions": []}
        report = render_report(res)
        section = report.split("## Flaky questions")[1]
        section = section.split("\n## ", 1)[0]
        self.assertIn("system_a: **1 flaky question(s)**", section)
        self.assertIn("| q001 | count_total | easy | 2/3 |", section)
        self.assertIn("system_b: **0 flaky questions**", section)

    def test_report_without_flaky_data_omits_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        for name in ("system_a", "system_b"):
            del res["systems"][name]["flaky_questions"]
        self.assertNotIn("## Flaky questions", render_report(res))

    def test_cli_writes_flaky_report_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "3", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            for name in ("system_a", "system_b"):
                self.assertEqual(
                    res["systems"][name]["flaky_questions"]["runs"], 3)
                self.assertEqual(
                    res["systems"][name]["flaky_questions"]["flaky_count"], 0)
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Flaky questions", f.read())


if __name__ == "__main__":
    unittest.main()
