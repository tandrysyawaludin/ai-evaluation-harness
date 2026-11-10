"""Per-question win/loss table for the paired system comparison."""
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
from evalharness.run_eval import build_win_loss, render_report, run


def _record(qid, correct, category="count_total", difficulty="easy"):
    return {"id": qid, "category": category, "difficulty": difficulty,
            "execution_correct": correct}


class TestBuildWinLoss(unittest.TestCase):
    def test_counts_and_outcomes(self):
        a = [_record("q1", True), _record("q2", False),
             _record("q3", False), _record("q4", True)]
        b = [_record("q1", True), _record("q2", True),
             _record("q3", False), _record("q4", False)]
        wl = build_win_loss(a, b)
        self.assertEqual(wl["n"], 4)
        self.assertEqual(wl["counts"], {"b_only": 1, "a_only": 1,
                                        "both_wrong": 1, "both_correct": 1})
        by_id = {r["id"]: r for r in wl["rows"]}
        self.assertEqual(by_id["q1"]["outcome"], "both_correct")
        self.assertEqual(by_id["q2"]["outcome"], "b_only")
        self.assertEqual(by_id["q3"]["outcome"], "both_wrong")
        self.assertEqual(by_id["q4"]["outcome"], "a_only")
        self.assertTrue(by_id["q2"]["system_b_correct"])
        self.assertFalse(by_id["q2"]["system_a_correct"])
        self.assertEqual(by_id["q2"]["category"], "count_total")
        self.assertEqual(by_id["q2"]["difficulty"], "easy")

    def test_discordant_rows_come_first_sorted_by_id(self):
        a = [_record("q3", True), _record("q1", False), _record("q2", True)]
        b = [_record("q3", False), _record("q1", True), _record("q2", True)]
        wl = build_win_loss(a, b)
        # q1: B wins, q3: A wins, q2: both correct — discordant first.
        self.assertEqual([r["id"] for r in wl["rows"]], ["q1", "q3", "q2"])

    def test_mismatched_counts_rejected(self):
        with self.assertRaises(ValueError):
            build_win_loss([_record("q1", True)], [])

    def test_misaligned_ids_rejected(self):
        with self.assertRaises(ValueError):
            build_win_loss([_record("q1", True)], [_record("q2", True)])

    def test_empty_input(self):
        wl = build_win_loss([], [])
        self.assertEqual(wl["n"], 0)
        self.assertEqual(wl["counts"], {"b_only": 0, "a_only": 0,
                                        "both_wrong": 0, "both_correct": 0})
        self.assertEqual(wl["rows"], [])


class TestRunWinLoss(unittest.TestCase):
    def test_run_carries_win_loss_matching_mcnemar(self):
        res = run(runs=1, seed=42)
        wl = res["comparison"]["win_loss"]
        self.assertEqual(wl["n"], res["gold_size"])
        self.assertEqual(sum(wl["counts"].values()), res["gold_size"])
        mc = res["comparison"]["mcnemar"]
        # Discordant counts are exactly McNemar's b and c.
        self.assertEqual(wl["counts"]["b_only"], mc["b"])
        self.assertEqual(wl["counts"]["a_only"], mc["c"])
        self.assertEqual(
            wl["counts"]["both_correct"],
            res["systems"]["system_a"]["correct"] - mc["c"])
        # Known headline numbers for this gold set: A 29/65, B 65/65.
        self.assertEqual(wl["counts"], {"b_only": 36, "a_only": 0,
                                        "both_wrong": 0, "both_correct": 29})

    def test_report_renders_win_loss_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Per-question win/loss (paired comparison)", report)
        self.assertIn("36 B only (McNemar b), 0 A only (McNemar c)", report)
        self.assertIn("Both correct", report)
        # Every gold question appears exactly once in the win/loss table
        # (scoped to that section: the error-analysis table below also
        # has | qNNN | rows).
        section = report.split("## Per-question win/loss")[1]
        section = section.split("\n## ", 1)[0]
        table_rows = [line for line in section.splitlines()
                      if line.startswith("| q")]
        self.assertEqual(len(table_rows), 65)
        self.assertEqual(len({line.split("|")[1].strip()
                              for line in table_rows}), 65)
        # Discordant rows lead: the first table row is a B win.
        self.assertIn("B wins", table_rows[0])

    def test_report_without_win_loss_omits_section(self):
        # Results files written before this feature have no win_loss key.
        res = run(runs=1, seed=42)
        del res["comparison"]["win_loss"]
        self.assertNotIn("## Per-question win/loss", render_report(res))

    def test_cli_writes_win_loss_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            self.assertEqual(res["comparison"]["win_loss"]["n"], 65)
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Per-question win/loss", f.read())


if __name__ == "__main__":
    unittest.main()
