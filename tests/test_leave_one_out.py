"""Leave-one-out headline sensitivity: how much each system's accuracy
and the B - A difference move when any single question is dropped,
in results.json and the report."""
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
from evalharness.run_eval import build_leave_one_out, render_report, run


def _records(flags):
    return [{"id": f"q{i + 1:03d}", "execution_correct": bool(f)}
            for i, f in enumerate(flags)]


class TestBuildLeaveOneOut(unittest.TestCase):
    def test_dropping_the_one_wrong_question_moves_most(self):
        # system_a 2/3: dropping the wrong question takes it to 2/2
        # (influence 1/3); dropping a right one takes it to 1/2
        # (influence 1/6). The wrong question is the most influential.
        a = _records([True, True, False])
        b = _records([True, True, True])
        loo = build_leave_one_out(a, b)
        self.assertEqual(loo["n"], 3)
        self.assertAlmostEqual(loo["system_a"]["overall"], 2 / 3)
        self.assertAlmostEqual(loo["system_a"]["max_influence"], 1 / 3)
        self.assertEqual(loo["system_a"]["most_influential_ids"], ["q003"])
        self.assertAlmostEqual(loo["system_a"]["value_without"], 1.0)
        # system_b is 3/3: dropping any question leaves it at 2/2.
        self.assertEqual(loo["system_b"]["max_influence"], 0.0)
        self.assertEqual(loo["system_b"]["most_influential_ids"],
                         ["q001", "q002", "q003"])
        self.assertEqual(loo["system_b"]["value_without"], 1.0)

    def test_difference_series_uses_per_question_differences(self):
        # A wrong / B right on q002 only: the difference is 1/3, and
        # dropping q002 takes it to 0 (influence 1/3); dropping a
        # both-correct question takes it to 1/2 (influence 1/6).
        a = _records([True, False, True])
        b = _records([True, True, True])
        loo = build_leave_one_out(a, b)
        diff = loo["difference_b_minus_a"]
        self.assertAlmostEqual(diff["overall"], 1 / 3)
        self.assertAlmostEqual(diff["max_influence"], 1 / 3)
        self.assertEqual(diff["most_influential_ids"], ["q002"])
        self.assertAlmostEqual(diff["value_without"], 0.0)

    def test_ties_list_every_tied_question(self):
        # 1/2 with one right and one wrong: dropping the right question
        # takes accuracy to 0/1 and dropping the wrong one to 1/1 — both
        # move it by exactly 1/2, so both questions tie.
        a = _records([True, False])
        b = _records([True, True])
        loo = build_leave_one_out(a, b)
        self.assertAlmostEqual(loo["system_a"]["max_influence"], 1 / 2)
        self.assertEqual(loo["system_a"]["most_influential_ids"],
                         ["q001", "q002"])
        # The representative value-without is the first tied id's:
        # dropping q001 (right) leaves 0/1.
        self.assertAlmostEqual(loo["system_a"]["value_without"], 0.0)
        # Same tie in the difference series: diffs are [0, 1].
        diff = loo["difference_b_minus_a"]
        self.assertAlmostEqual(diff["max_influence"], 1 / 2)
        self.assertEqual(diff["most_influential_ids"], ["q001", "q002"])
        self.assertAlmostEqual(diff["value_without"], 1.0)

    def test_single_question_has_nothing_to_leave_out(self):
        a = _records([True])
        b = _records([False])
        loo = build_leave_one_out(a, b)
        self.assertEqual(loo["n"], 1)
        for series in (loo["system_a"], loo["system_b"],
                       loo["difference_b_minus_a"]):
            self.assertEqual(series["max_influence"], 0.0)
            self.assertEqual(series["most_influential_ids"], [])
            self.assertIsNone(series["value_without"])

    def test_mismatched_records_raise(self):
        a = _records([True, False])
        b = _records([True])
        with self.assertRaises(ValueError):
            build_leave_one_out(a, b)
        b = [{"id": "q001", "execution_correct": True},
             {"id": "q999", "execution_correct": False}]
        with self.assertRaises(ValueError):
            build_leave_one_out(a, b)


class TestRunLeaveOneOut(unittest.TestCase):
    def test_run_carries_leave_one_out(self):
        res = run(runs=1, seed=42)
        loo = res["leave_one_out"]
        self.assertEqual(loo["n"], 65)
        # system_a 29/65: dropping a right question moves it to 28/64
        # (influence 29/65 - 28/64); dropping a wrong one moves it less.
        a = loo["system_a"]
        self.assertAlmostEqual(a["overall"], 29 / 65)
        self.assertAlmostEqual(a["max_influence"], 29 / 65 - 28 / 64)
        self.assertEqual(len(a["most_influential_ids"]), 29)
        self.assertEqual(a["most_influential_ids"][0], "q001")
        self.assertAlmostEqual(a["value_without"], 28 / 64)
        # system_b 65/65: dropping any question leaves it at 64/64.
        b = loo["system_b"]
        self.assertEqual(b["overall"], 1.0)
        self.assertEqual(b["max_influence"], 0.0)
        self.assertEqual(len(b["most_influential_ids"]), 65)
        self.assertEqual(b["value_without"], 1.0)
        # Difference 36/65: dropping a both-correct question (diff 0)
        # moves it to 36/64 — more than dropping a discordant one.
        d = loo["difference_b_minus_a"]
        self.assertAlmostEqual(d["overall"], 36 / 65)
        self.assertAlmostEqual(d["max_influence"], 36 / 64 - 36 / 65)
        self.assertEqual(len(d["most_influential_ids"]), 29)
        self.assertAlmostEqual(d["value_without"], 36 / 64)

    def test_report_renders_leave_one_out_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Leave-one-out sensitivity", report)
        self.assertIn("With 65 questions, one question can move an "
                      "accuracy by at most 1.5%", report)
        self.assertIn("| system_a accuracy | 44.6% | 43.8% | 0.9% | "
                      "q001 (29 tie) |", report)
        self.assertIn("| system_b accuracy | 100.0% | 100.0% | 0.0% | "
                      "q001 (65 tie) |", report)
        self.assertIn("| B − A difference | +55.4% | +56.2% | 0.9% | "
                      "q001 (29 tie) |", report)
        self.assertIn("The most sensitive headline number moves by at "
                      "most 0.9% when one question is dropped.", report)

    def test_report_without_leave_one_out_renders_no_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        res.pop("leave_one_out", None)
        report = render_report(res)
        self.assertNotIn("Leave-one-out sensitivity", report)
        # The rest of the report still renders.
        self.assertIn("## Headline results", report)
        self.assertIn("## Error analysis — system_a", report)

    def test_cli_writes_leave_one_out_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            loo = res["leave_one_out"]
            self.assertEqual(loo["n"], 65)
            self.assertAlmostEqual(loo["system_a"]["max_influence"],
                                   29 / 65 - 28 / 64)
            self.assertEqual(len(loo["system_b"]["most_influential_ids"]),
                             65)
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("## Leave-one-out sensitivity", report)
            self.assertIn("| system_a accuracy | 44.6% | 43.8% | 0.9% | "
                          "q001 (29 tie) |", report)


if __name__ == "__main__":
    unittest.main()
