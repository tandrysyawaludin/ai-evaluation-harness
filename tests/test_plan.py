import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness import plan


class TestPlan(unittest.TestCase):
    def test_n_shrinks_with_delta_and_grows_with_power(self):
        small = plan.plan(0.5, 0.10)
        large = plan.plan(0.5, 0.05)
        self.assertLess(small["n_per_group"], large["n_per_group"])
        self.assertGreater(plan.plan(0.5, 0.05, power=0.9)["n_per_group"],
                           plan.plan(0.5, 0.05, power=0.8)["n_per_group"])

    def test_target_is_baseline_plus_delta(self):
        p = plan.plan(0.53, 0.05)
        self.assertAlmostEqual(p["target"], 0.58)

    def test_invalid_proportions_raise(self):
        with self.assertRaises(ValueError):
            plan.plan(0.95, 0.10)
        with self.assertRaises(ValueError):
            plan.plan(0.0, 0.05)

    def test_current_n_verdict_and_shortfall(self):
        enough = plan.plan(0.5, 0.05, current_n=10_000)
        self.assertTrue(enough["sufficient"])
        self.assertEqual(enough["shortfall"], 0)
        short = plan.plan(0.5, 0.05, current_n=10)
        self.assertFalse(short["sufficient"])
        self.assertEqual(short["shortfall"],
                         short["n_per_group"] - 10)

    def test_table_covers_every_delta_and_power(self):
        rows = plan.plan_table(0.5, deltas=(0.05, 0.10), powers=(0.8, 0.9))
        self.assertEqual(len(rows), 4)
        self.assertEqual({(r["delta"], r["power"]) for r in rows},
                         {(0.05, 0.8), (0.05, 0.9), (0.10, 0.8), (0.10, 0.9)})

    def test_baseline_from_results_file(self):
        fake = {"gold_size": 55,
                "systems": {"system_a": {"execution_accuracy": 0.527}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            json.dump(fake, f)
            path = f.name
        try:
            accuracy, n = plan.baseline_from_results(path)
        finally:
            os.unlink(path)
        self.assertAlmostEqual(accuracy, 0.527)
        self.assertEqual(n, 55)

    def test_main_single_plan_prints_n(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(plan.main(["--baseline", "0.53",
                                        "--delta", "0.05"]), 0)
        self.assertIn("Gold questions needed", buf.getvalue())

    def test_main_from_results_uses_current_gold_size(self):
        results_path = os.path.join(os.path.dirname(__file__), "..",
                                    "results", "results.json")
        with open(results_path) as f:
            gold_size = json.load(f)["gold_size"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(plan.main(["--from-results", results_path]), 0)
        self.assertIn(f"Current gold set ({gold_size})", buf.getvalue())

    def test_main_table_and_json_modes(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(plan.main(["--baseline", "0.5", "--table"]), 0)
        self.assertIn("power 80%", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(plan.main(["--baseline", "0.5", "--json"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["n_per_group"],
                         plan.plan(0.5, 0.05)["n_per_group"])

    def test_main_requires_baseline_without_results(self):
        with self.assertRaises(SystemExit) as cm:
            plan.main([])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
