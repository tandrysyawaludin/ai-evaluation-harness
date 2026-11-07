import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness.compare import compare_results, render_compare
from evalharness import run_eval


def make_results(seed=42, a_correct=None, b_correct=None, kappa=0.55):
    """Minimal results.json-shaped dict over 4 gold questions."""
    def records(correct_flags):
        return [
            {"id": f"q{i}", "category": "counts" if i < 2 else "sums",
             "difficulty": "easy" if i % 2 == 0 else "hard",
             "execution_correct": bool(c)}
            for i, c in enumerate(correct_flags, start=1)
        ]
    def system(flags):
        return {
            "n": len(flags), "correct": sum(flags),
            "execution_accuracy": sum(flags) / len(flags),
            "latency": {"mean_ms": 0.10, "p95_ms": 0.20},
            "error_counts": {"wrong_filter": len(flags) - sum(flags)},
            "records": records(flags),
        }
    a_correct = a_correct if a_correct is not None else [0, 1, 1, 0]
    b_correct = b_correct if b_correct is not None else [1, 1, 1, 1]
    return {
        "gold_size": 4, "db_seed": seed,
        "systems": {"system_a": system(a_correct),
                    "system_b": system(b_correct)},
        "judge_calibration": ({"cohens_kappa": kappa} if kappa is not None
                              else None),
    }


class TestCompare(unittest.TestCase):
    def test_identical_runs_have_zero_deltas(self):
        diff = compare_results(make_results(), make_results())
        for name in ("system_a", "system_b"):
            s = diff["systems"][name]
            self.assertEqual(s["delta"], 0.0)
            self.assertEqual(s["fixed"], [])
            self.assertEqual(s["regressed"], [])
            self.assertEqual(s["mcnemar"]["p_value"], 1.0)
            self.assertEqual(s["error_delta"], {})
        self.assertEqual(diff["judge_kappa"]["delta"], 0.0)
        self.assertTrue(diff["same_db_seed"])

    def test_flips_detected_with_direction(self):
        old = make_results(a_correct=[0, 1, 1, 0])
        new = make_results(a_correct=[1, 1, 0, 0])
        s = compare_results(old, new)["systems"]["system_a"]
        self.assertEqual([f["id"] for f in s["fixed"]], ["q1"])
        self.assertEqual([f["id"] for f in s["regressed"]], ["q3"])
        self.assertEqual(s["fixed"][0]["category"], "counts")
        self.assertEqual(s["regressed"][0]["difficulty"], "hard")
        self.assertAlmostEqual(s["delta"], 0.0)  # one fix, one regression
        self.assertEqual((s["mcnemar"]["b"], s["mcnemar"]["c"]), (1, 1))

    def test_accuracy_delta_and_category_delta(self):
        old = make_results(a_correct=[0, 0, 1, 1])
        new = make_results(a_correct=[1, 1, 1, 1])
        s = compare_results(old, new)["systems"]["system_a"]
        self.assertAlmostEqual(s["delta"], 0.5)
        self.assertEqual(s["old_correct"], 2)
        self.assertEqual(s["new_correct"], 4)
        cats = s["per_category"]
        self.assertAlmostEqual(cats["counts"]["delta"], 1.0)
        # sums: 2/3 -> 3/3, because q2 flips while q3/q4 stay right.
        self.assertAlmostEqual(cats["sums"]["delta"], 1 / 3)
        self.assertEqual(s["error_delta"], {"wrong_filter": -2})

    def test_judge_kappa_delta_and_missing_calibration(self):
        diff = compare_results(make_results(kappa=0.50),
                               make_results(kappa=0.60))
        self.assertAlmostEqual(diff["judge_kappa"]["delta"], 0.10)
        diff = compare_results(make_results(kappa=0.50),
                               make_results(kappa=None))
        self.assertIsNone(diff["judge_kappa"]["delta"])

    def test_mismatched_gold_sets_raise(self):
        old = make_results()
        new = make_results()
        new["systems"]["system_a"]["records"][0]["id"] = "qX"
        new["systems"]["system_b"]["records"][0]["id"] = "qX"
        with self.assertRaises(ValueError):
            compare_results(old, new)

    def test_render_flags_different_seeds_and_lists_flips(self):
        old = make_results(seed=42, a_correct=[0, 1, 1, 0])
        new = make_results(seed=7, a_correct=[1, 1, 1, 0])
        report = render_compare(compare_results(old, new))
        self.assertIn("DB seeds differ", report)
        self.assertIn("Fixed (wrong → right)", report)
        self.assertIn("q1 (counts, hard)", report)
        self.assertIn("system_a", report)
        self.assertIn("Judge Cohen's kappa", report)


class TestCompareCLI(unittest.TestCase):
    def test_compare_mode_diffs_files_and_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            old_path = os.path.join(d, "old.json")
            new_path = os.path.join(d, "new.json")
            out_path = os.path.join(d, "compare.md")
            for path, res in ((old_path, make_results(a_correct=[0, 1, 1, 0])),
                              (new_path, make_results(a_correct=[1, 1, 1, 0]))):
                with open(path, "w") as f:
                    json.dump(res, f)
            argv = ["run_eval", "--compare", old_path, new_path,
                    "--compare-out", out_path]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()) as out:
                    run_eval.main()
            self.assertIn("Fixed (wrong → right)", out.getvalue())
            self.assertTrue(os.path.exists(out_path))
            with open(out_path) as f:
                self.assertIn("q1 (counts, hard)", f.read())


if __name__ == "__main__":
    unittest.main()
