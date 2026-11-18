"""Difficulty-monotonicity check: accuracy should fall easy -> medium -> hard."""
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
from evalharness.run_eval import (build_difficulty_monotonicity,
                                  render_report, run)


def _per_diff(easy, medium, hard):
    return {
        "easy": {"n": 10, "system_a_accuracy": easy[0],
                 "system_b_accuracy": easy[1]},
        "medium": {"n": 10, "system_a_accuracy": medium[0],
                   "system_b_accuracy": medium[1]},
        "hard": {"n": 10, "system_a_accuracy": hard[0],
                 "system_b_accuracy": hard[1]},
    }


class TestBuildDifficultyMonotonicity(unittest.TestCase):
    def test_monotonic_when_accuracy_falls(self):
        m = build_difficulty_monotonicity(
            _per_diff((0.9, 1.0), (0.6, 0.8), (0.3, 0.5)))
        self.assertEqual(m["difficulties"], ["easy", "medium", "hard"])
        self.assertTrue(m["monotonic"])
        for name in ("system_a", "system_b"):
            self.assertTrue(m["systems"][name]["monotonic"])
            self.assertEqual(m["systems"][name]["violations"], [])

    def test_flat_accuracy_is_monotonic(self):
        # Equal accuracy on two difficulties is not an inversion:
        # the check flags harder beating easier, not ties.
        m = build_difficulty_monotonicity(
            _per_diff((0.5, 0.5), (0.5, 0.5), (0.5, 0.5)))
        self.assertTrue(m["monotonic"])

    def test_violation_names_the_pair_and_gap(self):
        # system_a: hard (0.4) beats medium (0.1); system_b is clean.
        m = build_difficulty_monotonicity(
            _per_diff((0.8, 1.0), (0.1, 0.7), (0.4, 0.6)))
        self.assertFalse(m["monotonic"])
        a = m["systems"]["system_a"]
        self.assertFalse(a["monotonic"])
        self.assertEqual(len(a["violations"]), 1)
        v = a["violations"][0]
        self.assertEqual(v["easier"], "medium")
        self.assertEqual(v["harder"], "hard")
        self.assertEqual(v["easier_accuracy"], 0.1)
        self.assertEqual(v["harder_accuracy"], 0.4)
        self.assertAlmostEqual(v["gap"], 0.3)
        self.assertEqual(v["easier_n"], 10)
        self.assertEqual(v["harder_n"], 10)
        self.assertTrue(m["systems"]["system_b"]["monotonic"])

    def test_both_pairs_can_violate(self):
        m = build_difficulty_monotonicity(
            _per_diff((0.2, 0.2), (0.5, 0.5), (0.9, 0.9)))
        for name in ("system_a", "system_b"):
            vs = m["systems"][name]["violations"]
            self.assertEqual([(v["easier"], v["harder"]) for v in vs],
                             [("easy", "medium"), ("medium", "hard")])

    def test_missing_difficulty_compares_across_the_gap(self):
        # No medium questions: easy is compared against hard directly.
        per_diff = {"easy": {"n": 10, "system_a_accuracy": 0.4,
                             "system_b_accuracy": 0.9},
                    "hard": {"n": 10, "system_a_accuracy": 0.6,
                             "system_b_accuracy": 0.8}}
        m = build_difficulty_monotonicity(per_diff)
        self.assertEqual(m["difficulties"], ["easy", "hard"])
        self.assertEqual(m["systems"]["system_a"]["violations"][0]["easier"],
                         "easy")
        self.assertEqual(m["systems"]["system_a"]["violations"][0]["harder"],
                         "hard")
        self.assertTrue(m["systems"]["system_b"]["monotonic"])

    def test_unknown_difficulty_label_is_ignored(self):
        per_diff = _per_diff((0.9, 1.0), (0.6, 0.8), (0.3, 0.5))
        per_diff["expert"] = {"n": 5, "system_a_accuracy": 1.0,
                              "system_b_accuracy": 1.0}
        m = build_difficulty_monotonicity(per_diff)
        self.assertEqual(m["difficulties"], ["easy", "medium", "hard"])
        self.assertTrue(m["monotonic"])


class TestRunDifficultyMonotonicity(unittest.TestCase):
    def test_run_carries_monotonicity(self):
        res = run(runs=1, seed=42)
        m = res["difficulty_monotonicity"]
        self.assertEqual(m["difficulties"], ["easy", "medium", "hard"])
        # system_b is 100% everywhere, so it is trivially monotonic.
        self.assertTrue(m["systems"]["system_b"]["monotonic"])
        # system_a on the real gold set: easy 58%, medium 0% (n=4),
        # hard 32% — hard beating medium is a real violation, and it
        # is the only one.
        a = m["systems"]["system_a"]
        self.assertFalse(a["monotonic"])
        self.assertEqual(len(a["violations"]), 1)
        v = a["violations"][0]
        self.assertEqual((v["easier"], v["harder"]), ("medium", "hard"))
        self.assertEqual(v["easier_accuracy"], 0.0)
        self.assertAlmostEqual(v["harder_accuracy"], 0.32)
        self.assertEqual(v["easier_n"], 4)
        self.assertEqual(v["harder_n"], 25)
        self.assertFalse(m["monotonic"])

    def test_report_renders_monotonicity_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Difficulty monotonicity", report)
        self.assertIn("- system_b: **monotonic**", report)
        self.assertIn("- system_a: **not monotonic** — hard 32% (n=25) "
                      "beats medium 0% (n=4) by 32%.", report)

    def test_report_without_monotonicity_data_omits_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        del res["difficulty_monotonicity"]
        self.assertNotIn("## Difficulty monotonicity", render_report(res))

    def test_cli_writes_monotonicity_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            m = res["difficulty_monotonicity"]
            self.assertFalse(m["systems"]["system_a"]["monotonic"])
            self.assertTrue(m["systems"]["system_b"]["monotonic"])
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Difficulty monotonicity", f.read())


if __name__ == "__main__":
    unittest.main()
