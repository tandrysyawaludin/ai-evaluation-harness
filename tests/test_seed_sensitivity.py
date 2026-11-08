"""Seed-sensitivity: headline metrics under a second database seed."""
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
from evalharness.run_eval import (DEFAULT_SEEDS, STABILITY_THRESHOLD,
                                  build_seed_sensitivity, render_report,
                                  run)


def _fake_seed_result(a_acc, b_acc, p=0.01, n=65):
    return {
        "systems": {
            "system_a": {"execution_accuracy": a_acc,
                         "correct": round(a_acc * n), "n": n},
            "system_b": {"execution_accuracy": b_acc,
                         "correct": round(b_acc * n), "n": n},
        },
        "comparison": {
            "accuracy_difference_b_minus_a": b_acc - a_acc,
            "mcnemar": {"p_value": p},
        },
    }


class TestBuildSeedSensitivity(unittest.TestCase):
    def test_spread_is_max_minus_min_and_stable_flag(self):
        per_seed = {
            42: _fake_seed_result(0.40, 1.00),
            1234: _fake_seed_result(0.46, 0.97),
        }
        sens = build_seed_sensitivity(per_seed)
        self.assertEqual(sens["seeds"], [42, 1234])
        self.assertAlmostEqual(sens["spread"]["system_a_accuracy"], 0.06)
        self.assertAlmostEqual(sens["spread"]["system_b_accuracy"], 0.03)
        self.assertAlmostEqual(
            sens["spread"]["accuracy_difference_b_minus_a"], 0.09)
        # system_a swings 6pp > 5pp threshold, so not stable.
        self.assertFalse(sens["stable"])
        self.assertEqual(sens["stability_threshold"], STABILITY_THRESHOLD)
        self.assertEqual(sens["per_seed"]["42"]["system_a_correct"], 26)
        self.assertAlmostEqual(
            sens["per_seed"]["1234"]["accuracy_difference_b_minus_a"], 0.51)

    def test_all_small_swings_are_stable(self):
        per_seed = {
            42: _fake_seed_result(0.40, 1.00),
            1234: _fake_seed_result(0.42, 0.99),
        }
        sens = build_seed_sensitivity(per_seed)
        self.assertTrue(sens["stable"])

    def test_three_seeds_use_full_range(self):
        per_seed = {
            1: _fake_seed_result(0.40, 1.00),
            2: _fake_seed_result(0.50, 0.95),
            3: _fake_seed_result(0.45, 0.98),
        }
        sens = build_seed_sensitivity(per_seed)
        self.assertAlmostEqual(sens["spread"]["system_a_accuracy"], 0.10)
        self.assertEqual(sens["seeds"], [1, 2, 3])


class TestRunWithSeeds(unittest.TestCase):
    def test_two_seed_run_reports_sensitivity(self):
        res = run(runs=1, seeds=(42, 1234))
        self.assertEqual(res["db_seed"], 42)
        self.assertEqual(res["db_seeds"], [42, 1234])
        sens = res["seed_sensitivity"]
        self.assertIsNotNone(sens)
        self.assertEqual(sens["seeds"], [42, 1234])
        self.assertEqual(set(sens["per_seed"]), {"42", "1234"})
        for s in sens["per_seed"].values():
            self.assertEqual(s["n"], res["gold_size"])
            self.assertTrue(0.0 <= s["system_a_accuracy"] <= 1.0)
            self.assertTrue(0.0 <= s["system_b_accuracy"] <= 1.0)
        # Primary block is the first seed's full results.
        self.assertEqual(
            res["systems"]["system_b"]["execution_accuracy"],
            sens["per_seed"]["42"]["system_b_accuracy"])
        # Judge calibration is seed-independent: computed once, on the
        # primary seed, and still present.
        self.assertIsNotNone(res["judge_calibration"])

    def test_single_seed_run_has_no_sensitivity(self):
        res = run(runs=1, seed=42)
        self.assertEqual(res["db_seeds"], [42])
        self.assertIsNone(res["seed_sensitivity"])

    def test_empty_seeds_rejected(self):
        with self.assertRaises(ValueError):
            run(runs=1, seeds=())

    def test_default_seeds_are_two(self):
        self.assertEqual(len(DEFAULT_SEEDS), 2)
        self.assertIn(42, DEFAULT_SEEDS)


class TestReportAndCli(unittest.TestCase):
    def test_report_renders_sensitivity_section(self):
        res = run(runs=1, seeds=(42, 1234))
        report = render_report(res)
        self.assertIn("## Seed sensitivity", report)
        self.assertIn("42", report)
        self.assertIn("1234", report)
        self.assertIn("Verdict: the headline metrics are", report)

    def test_report_without_sensitivity_omits_section(self):
        res = run(runs=1, seed=42)
        self.assertNotIn("## Seed sensitivity", render_report(res))

    def test_cli_seeds_flag_writes_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seeds", "42", "1234",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            self.assertEqual(res["db_seeds"], [42, 1234])
            self.assertIsNotNone(res["seed_sensitivity"])
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Seed sensitivity", f.read())

    def test_cli_single_seed_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "7",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            self.assertEqual(res["db_seed"], 7)
            self.assertEqual(res["db_seeds"], [7])
            self.assertIsNone(res["seed_sensitivity"])


if __name__ == "__main__":
    unittest.main()
