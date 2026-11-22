"""Per-difficulty Wilson 95% CIs in the per-difficulty accuracy table."""
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
from evalharness.run_eval import build_per_difficulty, render_report, run
from evalharness.stats import wilson_interval


def _item(i, difficulty):
    return {"id": f"q{i}", "difficulty": difficulty}


def _rec(i, correct):
    return {"id": f"q{i}", "execution_correct": correct}


class TestBuildPerDifficulty(unittest.TestCase):
    def test_accuracies_and_correct_counts(self):
        gold = [_item(0, "easy"), _item(1, "easy"), _item(2, "hard"),
                _item(3, "hard"), _item(4, "hard")]
        ra = [_rec(0, True), _rec(1, False), _rec(2, True),
              _rec(3, True), _rec(4, True)]
        rb = [_rec(0, True), _rec(1, True), _rec(2, True),
              _rec(3, True), _rec(4, False)]
        diffs = build_per_difficulty(gold, ra, rb)
        self.assertEqual(diffs["easy"]["n"], 2)
        self.assertEqual(diffs["easy"]["system_a_correct"], 1)
        self.assertEqual(diffs["easy"]["system_b_correct"], 2)
        self.assertEqual(diffs["easy"]["system_a_accuracy"], 0.5)
        self.assertEqual(diffs["easy"]["system_b_accuracy"], 1.0)
        self.assertEqual(diffs["hard"]["n"], 3)
        self.assertEqual(diffs["hard"]["system_a_accuracy"], 1.0)
        self.assertAlmostEqual(diffs["hard"]["system_b_accuracy"], 2 / 3)

    def test_ci_matches_wilson_interval(self):
        # 3 of 4 right on easy, 0 of 2 on hard: the CI must be exactly
        # stats.wilson_interval on the same counts, so the table and
        # the accuracy can never disagree.
        gold = [_item(i, "easy" if i < 4 else "hard") for i in range(6)]
        ra = [_rec(i, i < 3) for i in range(6)]
        rb = [_rec(i, True) for i in range(6)]
        diffs = build_per_difficulty(gold, ra, rb)
        self.assertEqual(diffs["easy"]["system_a_wilson_95ci"],
                         wilson_interval(3, 4))
        self.assertEqual(diffs["easy"]["system_b_wilson_95ci"],
                         wilson_interval(4, 4))
        self.assertEqual(diffs["hard"]["system_a_wilson_95ci"],
                         wilson_interval(0, 2))
        self.assertEqual(diffs["hard"]["system_b_wilson_95ci"],
                         wilson_interval(2, 2))

    def test_ci_contains_accuracy_and_stays_in_unit_interval(self):
        gold = [_item(i, "easy" if i < 4 else "hard") for i in range(6)]
        ra = [_rec(i, i < 3) for i in range(6)]
        rb = [_rec(i, True) for i in range(6)]
        for diff, v in build_per_difficulty(gold, ra, rb).items():
            for name in ("system_a", "system_b"):
                lo, hi = v[f"{name}_wilson_95ci"]
                self.assertGreaterEqual(lo, 0.0)
                self.assertLessEqual(hi, 1.0)
                self.assertLessEqual(lo, v[f"{name}_accuracy"])
                self.assertGreaterEqual(hi, v[f"{name}_accuracy"])

    def test_small_n_means_wide_ci(self):
        # The whole point: 1/1 and 10/10 are both 100%, but only the
        # second says anything. A single-question difficulty's interval
        # must be far wider than a ten-question one's.
        gold = [_item(0, "medium")] + [_item(i, "easy") for i in range(1, 11)]
        ra = [_rec(i, True) for i in range(11)]
        rb = [_rec(i, True) for i in range(11)]
        diffs = build_per_difficulty(gold, ra, rb)
        tiny_lo, tiny_hi = diffs["medium"]["system_a_wilson_95ci"]
        big_lo, big_hi = diffs["easy"]["system_a_wilson_95ci"]
        self.assertEqual(diffs["medium"]["system_a_accuracy"], 1.0)
        self.assertEqual(diffs["easy"]["system_a_accuracy"], 1.0)
        self.assertGreater(tiny_hi - tiny_lo, big_hi - big_lo)
        self.assertAlmostEqual(tiny_lo, 0.207, places=3)
        self.assertAlmostEqual(big_lo, 0.722, places=3)

    def test_difficulties_ordered_easy_medium_hard(self):
        gold = [_item(0, "hard"), _item(1, "easy"), _item(2, "medium"),
                _item(3, "tricky")]
        ra = [_rec(i, True) for i in range(4)]
        rb = [_rec(i, True) for i in range(4)]
        self.assertEqual(list(build_per_difficulty(gold, ra, rb)),
                         ["easy", "medium", "hard", "tricky"])

    def test_misaligned_records_raise(self):
        gold = [_item(0, "easy"), _item(1, "easy")]
        ra = [_rec(0, True), _rec(1, True)]
        rb = [_rec(0, True)]
        with self.assertRaises(ValueError):
            build_per_difficulty(gold, ra, rb)
        rb_bad = [_rec(0, True), _rec(9, True)]
        with self.assertRaises(ValueError):
            build_per_difficulty(gold, ra, rb_bad)


class TestRunPerDifficultyCI(unittest.TestCase):
    def test_run_carries_per_difficulty_cis(self):
        res = run(runs=1, seed=42)
        diffs = res["per_difficulty"]
        # easy: system_a 21/36, system_b 36/36; medium: 0/4 and 4/4;
        # hard: 8/25 and 25/25.
        self.assertEqual(list(diffs), ["easy", "medium", "hard"])
        easy = diffs["easy"]
        self.assertEqual(easy["n"], 36)
        self.assertEqual(easy["system_a_correct"], 21)
        self.assertEqual(easy["system_b_correct"], 36)
        self.assertEqual([round(x, 3) for x in
                          easy["system_a_wilson_95ci"]], [0.422, 0.729])
        self.assertEqual([round(x, 3) for x in
                          easy["system_b_wilson_95ci"]], [0.904, 1.0])
        medium = diffs["medium"]
        self.assertEqual(medium["n"], 4)
        self.assertEqual([round(x, 3) for x in
                          medium["system_a_wilson_95ci"]], [0.0, 0.490])
        self.assertEqual([round(x, 3) for x in
                          medium["system_b_wilson_95ci"]], [0.510, 1.0])
        hard = diffs["hard"]
        self.assertEqual(hard["n"], 25)
        self.assertEqual([round(x, 3) for x in
                          hard["system_a_wilson_95ci"]], [0.172, 0.516])
        self.assertEqual([round(x, 3) for x in
                          hard["system_b_wilson_95ci"]], [0.867, 1.0])
        # Every difficulty carries both CIs, and each CI contains its
        # accuracy.
        for diff, v in diffs.items():
            for name in ("system_a", "system_b"):
                lo, hi = v[f"{name}_wilson_95ci"]
                self.assertLessEqual(lo, v[f"{name}_accuracy"])
                self.assertGreaterEqual(hi, v[f"{name}_accuracy"])

    def test_report_renders_ci_columns(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Per-difficulty accuracy", report)
        self.assertIn("| Difficulty | n | system_a | system_a 95% Wilson CI "
                      "| system_b | system_b 95% Wilson CI |", report)
        self.assertIn("| easy | 36 | 58% | [0.422, 0.729] "
                      "| 100% | [0.904, 1.000] |", report)
        self.assertIn("| medium | 4 | 0% | [0.000, 0.490] "
                      "| 100% | [0.510, 1.000] |", report)
        self.assertIn("| hard | 25 | 32% | [0.172, 0.516] "
                      "| 100% | [0.867, 1.000] |", report)

    def test_report_without_ci_data_renders_dash(self):
        # Results files written before this feature have no CI keys.
        res = run(runs=1, seed=42)
        for v in res["per_difficulty"].values():
            v.pop("system_a_wilson_95ci", None)
            v.pop("system_b_wilson_95ci", None)
        report = render_report(res)
        self.assertIn("| easy | 36 | 58% | — "
                      "| 100% | — |", report)

    def test_cli_writes_cis_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            easy = res["per_difficulty"]["easy"]
            # Tuples serialise as JSON lists; the values survive.
            self.assertEqual([round(x, 3) for x in
                              easy["system_a_wilson_95ci"]], [0.422, 0.729])
            self.assertEqual([round(x, 3) for x in
                              easy["system_b_wilson_95ci"]], [0.904, 1.0])
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("system_a 95% Wilson CI", report)
            self.assertIn("| medium | 4 | 0% | [0.000, 0.490] "
                          "| 100% | [0.510, 1.000] |", report)


if __name__ == "__main__":
    unittest.main()
