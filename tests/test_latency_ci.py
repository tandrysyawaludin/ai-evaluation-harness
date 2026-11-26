"""Bootstrap CI for per-system mean latency, in results and the report."""
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
from evalharness.run_eval import render_report, run
from evalharness.stats import bootstrap_ci, latency_summary


class TestLatencySummaryCI(unittest.TestCase):
    def test_ci_matches_bootstrap_on_same_values(self):
        # The CI must be exactly stats.bootstrap_ci on the same
        # per-question latencies, so the table and the summary can
        # never disagree.
        values = [0.5, 0.6, 0.4, 1.2, 0.9, 0.7, 0.8, 0.55, 0.65, 0.75]
        summary = latency_summary(values)
        self.assertEqual(summary["mean_bootstrap_95ci"],
                         bootstrap_ci(values))
        self.assertAlmostEqual(summary["mean_ms"],
                               sum(values) / len(values))
        self.assertEqual(summary["p95_ms"], 1.2)

    def test_empty_latencies_have_degenerate_ci(self):
        self.assertEqual(latency_summary([]),
                         {"mean_ms": 0.0, "p95_ms": 0.0,
                          "mean_bootstrap_95ci": (0.0, 0.0)})

    def test_constant_latencies_collapse_ci(self):
        # Every question took the same time: the mean is that time on
        # every resample, so the interval collapses to a point.
        summary = latency_summary([0.3] * 8)
        self.assertEqual(summary["mean_bootstrap_95ci"], (0.3, 0.3))

    def test_ci_contains_mean(self):
        values = [0.5, 0.6, 0.4, 1.2, 0.9, 0.7, 0.8, 0.55, 0.65, 0.75]
        lo, hi = latency_summary(values)["mean_bootstrap_95ci"]
        self.assertLessEqual(lo, sum(values) / len(values))
        self.assertGreaterEqual(hi, sum(values) / len(values))

    def test_ci_widens_with_a_slow_tail(self):
        # Same fast questions, plus two very slow ones: the mean rises
        # and its interval widens — the CI is doing its job of saying
        # how much the tail drives the mean.
        fast = [0.1] * 20
        tailed = fast + [5.0, 6.0]
        lo_fast, hi_fast = latency_summary(fast)["mean_bootstrap_95ci"]
        lo_tail, hi_tail = latency_summary(tailed)["mean_bootstrap_95ci"]
        self.assertEqual((lo_fast, hi_fast), (0.1, 0.1))
        self.assertGreater(hi_tail - lo_tail, hi_fast - lo_fast)
        self.assertGreater(latency_summary(tailed)["mean_ms"],
                           latency_summary(fast)["mean_ms"])

    def test_deterministic_across_calls(self):
        values = [0.5, 0.6, 0.4, 1.2, 0.9, 0.7, 0.8, 0.55, 0.65, 0.75]
        self.assertEqual(latency_summary(values),
                         latency_summary(values))


class TestRunLatencyCI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(runs=1, seed=42)

    def test_run_carries_latency_cis(self):
        for name in ("system_a", "system_b"):
            lat = self.res["systems"][name]["latency"]
            ci = lat["mean_bootstrap_95ci"]
            self.assertEqual(len(ci), 2)
            lo, hi = ci
            self.assertLessEqual(lo, lat["mean_ms"])
            self.assertGreaterEqual(hi, lat["mean_ms"])
            self.assertLessEqual(lo, hi)
            self.assertGreaterEqual(lo, 0.0)

    def test_report_renders_latency_ci_column(self):
        report = render_report(self.res)
        self.assertIn("## Latency", report)
        self.assertIn("| System | Mean | Mean 95% bootstrap CI | p95 |",
                      report)
        for name in ("system_a", "system_b"):
            lat = self.res["systems"][name]["latency"]
            ci = lat["mean_bootstrap_95ci"]
            self.assertIn(
                f"| {name} | {lat['mean_ms']:.2f} ms | "
                f"[{ci[0]:.2f}, {ci[1]:.2f}] ms | "
                f"{lat['p95_ms']:.2f} ms |", report)
        self.assertIn("bootstrap CI is the uncertainty on the mean",
                      report)

    def test_report_without_latency_ci_renders_dash(self):
        # Results files written before this feature have no CI key.
        res = json.loads(json.dumps(self.res))
        for name in ("system_a", "system_b"):
            res["systems"][name]["latency"].pop("mean_bootstrap_95ci")
        report = render_report(res)
        self.assertIn("| system_a | ", report)
        self.assertIn("| — |", report)

    def test_cli_writes_latency_cis_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            for name in ("system_a", "system_b"):
                lat = res["systems"][name]["latency"]
                # Tuples serialise as JSON lists; the values survive.
                ci = lat["mean_bootstrap_95ci"]
                self.assertEqual(len(ci), 2)
                self.assertLessEqual(ci[0], lat["mean_ms"])
                self.assertGreaterEqual(ci[1], lat["mean_ms"])
            with open(os.path.join(tmp, "report.md")) as f:
                report = f.read()
            self.assertIn("Mean 95% bootstrap CI", report)


if __name__ == "__main__":
    unittest.main()
