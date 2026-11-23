"""Stratified headline accuracy: equal-weight mean of the
per-difficulty accuracies, in results.json and the report."""
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
from evalharness.run_eval import build_stratified_accuracy, render_report, run


def _per_difficulty(accs):
    return {d: {"n": 10, f"system_a_accuracy": a, f"system_b_accuracy": b}
            for d, (a, b) in accs.items()}


class TestBuildStratifiedAccuracy(unittest.TestCase):
    def test_equal_weight_mean_not_question_weighted(self):
        # Easy holds most questions in the real gold set (36/65), so a
        # question-weighted mean would track easy; the stratified mean
        # must give each difficulty one vote whatever its n.
        diffs = _per_difficulty({"easy": (0.9, 1.0), "medium": (0.0, 1.0),
                                 "hard": (0.3, 1.0)})
        strat = build_stratified_accuracy(diffs)
        self.assertEqual(strat["difficulties"], ["easy", "medium", "hard"])
        self.assertAlmostEqual(strat["system_a_stratified_accuracy"],
                               (0.9 + 0.0 + 0.3) / 3)
        self.assertEqual(strat["system_b_stratified_accuracy"], 1.0)
        self.assertAlmostEqual(strat["stratified_difference_b_minus_a"],
                               1.0 - (0.9 + 0.0 + 0.3) / 3)

    def test_single_difficulty_equals_its_accuracy(self):
        diffs = _per_difficulty({"easy": (0.75, 0.5)})
        strat = build_stratified_accuracy(diffs)
        self.assertEqual(strat["system_a_stratified_accuracy"], 0.75)
        self.assertEqual(strat["system_b_stratified_accuracy"], 0.5)
        self.assertAlmostEqual(strat["stratified_difference_b_minus_a"],
                               -0.25)

    def test_empty_breakdown_is_zero(self):
        strat = build_stratified_accuracy({})
        self.assertEqual(strat["difficulties"], [])
        self.assertEqual(strat["system_a_stratified_accuracy"], 0.0)
        self.assertEqual(strat["system_b_stratified_accuracy"], 0.0)
        self.assertEqual(strat["stratified_difference_b_minus_a"], 0.0)

    def test_easy_heavy_set_cannot_inflate_stratified(self):
        # system_a is strong only on easy (0.9) and weak elsewhere
        # (0.1, 0.1): its headline over an easy-heavy set would be near
        # 0.9, but the stratified accuracy must stay at the plain mean.
        diffs = _per_difficulty({"easy": (0.9, 0.9), "medium": (0.1, 0.9),
                                 "hard": (0.1, 0.9)})
        strat = build_stratified_accuracy(diffs)
        self.assertAlmostEqual(strat["system_a_stratified_accuracy"],
                               (0.9 + 0.1 + 0.1) / 3)
        self.assertLess(strat["system_a_stratified_accuracy"], 0.5)


class TestRunStratifiedAccuracy(unittest.TestCase):
    def test_run_carries_stratified_accuracy(self):
        res = run(runs=1, seed=42)
        strat = res["stratified_accuracy"]
        self.assertEqual(strat["difficulties"], ["easy", "medium", "hard"])
        # easy: system_a 21/36, medium: 0/4, hard: 8/25; system_b 100%
        # on every difficulty.
        self.assertAlmostEqual(strat["system_a_stratified_accuracy"],
                               (21 / 36 + 0 / 4 + 8 / 25) / 3, places=4)
        self.assertEqual(strat["system_b_stratified_accuracy"], 1.0)
        self.assertAlmostEqual(strat["stratified_difference_b_minus_a"],
                               1.0 - (21 / 36 + 0 / 4 + 8 / 25) / 3,
                               places=4)
        # The headline (29/65 = 44.6%) overstates system_a by ~14.5pp
        # against the stratified number — that gap is the point.
        headline = res["systems"]["system_a"]["execution_accuracy"]
        self.assertAlmostEqual(
            headline - strat["system_a_stratified_accuracy"],
            29 / 65 - (21 / 36 + 0 / 4 + 8 / 25) / 3, places=4)
        self.assertGreater(
            headline - strat["system_a_stratified_accuracy"], 0.1)

    def test_report_renders_stratified_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Stratified headline accuracy", report)
        self.assertIn("easy n=36, medium n=4, hard n=25", report)
        self.assertIn("| System | Overall accuracy | Stratified accuracy "
                      "| Inflation (overall − stratified) |", report)
        self.assertIn("| system_a | 44.6% (29/65) | 30.1% | +14.5% |",
                      report)
        self.assertIn("| system_b | 100.0% (65/65) | 100.0% | +0.0% |",
                      report)
        self.assertIn("The stratified B − A difference is +69.9%, "
                      "against +55.4% overall.", report)

    def test_report_without_stratified_data_renders_no_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        res.pop("stratified_accuracy", None)
        report = render_report(res)
        self.assertNotIn("Stratified headline accuracy", report)
        # The rest of the report still renders.
        self.assertIn("## Headline results", report)
        self.assertIn("## Per-difficulty accuracy", report)

    def test_cli_writes_stratified_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            strat = res["stratified_accuracy"]
            self.assertEqual(strat["difficulties"],
                             ["easy", "medium", "hard"])
            self.assertAlmostEqual(strat["system_a_stratified_accuracy"],
                                   (21 / 36 + 0 / 4 + 8 / 25) / 3, places=4)
            self.assertEqual(strat["system_b_stratified_accuracy"], 1.0)
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("## Stratified headline accuracy", report)
            self.assertIn("| system_a | 44.6% (29/65) | 30.1% | +14.5% |",
                          report)


if __name__ == "__main__":
    unittest.main()
