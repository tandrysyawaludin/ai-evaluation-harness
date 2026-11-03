import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness import stats
from evalharness.metrics import exact_match, normalise_sql


class TestStats(unittest.TestCase):
    def test_wilson_contains_point_estimate(self):
        lo, hi = stats.wilson_interval(80, 100)
        self.assertLess(lo, 0.8)
        self.assertGreater(hi, 0.8)

    def test_wilson_perfect_score_high_lower_bound(self):
        lo, hi = stats.wilson_interval(55, 55)
        self.assertGreater(lo, 0.9)
        self.assertAlmostEqual(hi, 1.0)

    def test_bootstrap_ci_brackets_mean(self):
        lo, hi = stats.bootstrap_ci([0, 1] * 50, n_boot=500)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_mcnemar_no_discordance(self):
        r = stats.mcnemar([1, 1, 0], [1, 1, 0])
        self.assertEqual(r["p_value"], 1.0)

    def test_mcnemar_clear_winner_significant(self):
        a = [0] * 20 + [1] * 20
        b = [1] * 20 + [1] * 20
        r = stats.mcnemar(a, b)
        self.assertEqual((r["b"], r["c"]), (20, 0))
        self.assertLess(r["p_value"], 0.01)

    def test_sample_size_positive_and_shrinks_with_delta(self):
        self.assertGreater(stats.sample_size_for_difference(0.7, 0.05),
                           stats.sample_size_for_difference(0.7, 0.10))

    def test_percentile_nearest_rank(self):
        values = [10, 20, 30, 40]
        self.assertEqual(stats.percentile(values, 0), 10)
        self.assertEqual(stats.percentile(values, 50), 20)
        self.assertEqual(stats.percentile(values, 95), 40)
        self.assertEqual(stats.percentile(values, 100), 40)

    def test_percentile_empty_and_out_of_range(self):
        self.assertEqual(stats.percentile([], 95), 0.0)
        with self.assertRaises(ValueError):
            stats.percentile([1.0], 101)

    def test_latency_summary_mean_and_p95(self):
        summary = stats.latency_summary([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(summary["mean_ms"], 2.5)
        self.assertEqual(summary["p95_ms"], 4.0)
        self.assertEqual(stats.latency_summary([]),
                         {"mean_ms": 0.0, "p95_ms": 0.0})


class TestMetrics(unittest.TestCase):
    def test_normalise_sql(self):
        self.assertEqual(normalise_sql("  SELECT  *\nFROM t; "), "select * from t")

    def test_exact_match_ignores_case_and_whitespace(self):
        self.assertTrue(exact_match("SELECT COUNT(*) FROM orders",
                                    "select  count(*)  from orders;"))
        self.assertFalse(exact_match("SELECT a FROM t", "SELECT b FROM t"))


if __name__ == "__main__":
    unittest.main()
