import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness import stats
from evalharness.db import build_db
from evalharness.metrics import categorise_error, exact_match, normalise_sql
from evalharness.systems import system_a, system_b


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


class TestErrorTaxonomy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = build_db()

    def test_dropped_filter_is_wrong_filter(self):
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT COUNT(*) FROM orders",
                "SELECT COUNT(*) FROM orders WHERE side = 'BUY'"),
            "wrong_filter")

    def test_dropped_date_filter_is_wrong_filter(self):
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT COUNT(*) FROM orders WHERE symbol = 'AAPL'",
                "SELECT COUNT(*) FROM orders WHERE order_date BETWEEN "
                "'2025-04-01' AND '2025-04-30' AND symbol = 'AAPL'"),
            "wrong_filter")

    def test_wrong_aggregate_column_is_wrong_aggregation(self):
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT AVG(quantity) FROM orders WHERE symbol = 'AAPL'",
                "SELECT AVG(price) FROM orders WHERE symbol = 'AAPL'"),
            "wrong_aggregation")

    def test_missing_join_is_wrong_join(self):
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT COUNT(*) FROM orders",
                "SELECT COUNT(*) FROM orders o JOIN accounts a "
                "ON o.account_id = a.account_id JOIN clients cl "
                "ON a.client_id = cl.client_id "
                "WHERE cl.country = 'Japan'"),
            "wrong_join")

    def test_join_beats_filter_when_both_differ(self):
        # The country query is missing both the join and its filter; the
        # join is the root cause, so it wins.
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT SUM(quantity * price) FROM orders",
                "SELECT SUM(o.quantity * o.price) FROM orders o "
                "JOIN accounts a ON o.account_id = a.account_id "
                "JOIN clients cl ON a.client_id = cl.client_id "
                "WHERE cl.country = 'Japan'"),
            "wrong_join")

    def test_same_filter_in_different_order_is_not_an_error(self):
        self.assertIsNone(categorise_error(
            self.conn,
            "SELECT SUM(quantity) FROM orders "
            "WHERE symbol = 'AAPL' AND side = 'BUY'",
            "SELECT SUM(quantity) FROM orders "
            "WHERE side = 'BUY' AND symbol = 'AAPL'"))

    def test_wrong_limit_stays_generic_wrong_result(self):
        # Filter, join, and aggregation all match; only the LIMIT differs.
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT symbol FROM orders GROUP BY symbol "
                "ORDER BY SUM(quantity) DESC LIMIT 2",
                "SELECT symbol FROM orders GROUP BY symbol "
                "ORDER BY SUM(quantity) DESC LIMIT 1"),
            "wrong_result")

    def test_empty_result_and_execution_error_unchanged(self):
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT symbol FROM orders WHERE symbol = 'ZZZ'",
                "SELECT symbol FROM orders GROUP BY symbol "
                "ORDER BY SUM(quantity) DESC LIMIT 1"),
            "empty_result")
        self.assertEqual(
            categorise_error(
                self.conn,
                "SELECT * FROM nonexistent_table",
                "SELECT COUNT(*) FROM orders"),
            "execution_error")
        self.assertEqual(
            categorise_error(self.conn, None, "SELECT COUNT(*) FROM orders"),
            "no_sql_generated")

    def test_system_a_failures_all_get_a_specific_bucket(self):
        # Every documented system_a weakness maps to a finer bucket, and
        # none of its failures is left as generic wrong_result.
        from evalharness.gold import generate_gold
        from evalharness.metrics import evaluate_system
        gold = generate_gold()
        a = evaluate_system(self.conn, system_a, gold)
        errors = {r["error"] for r in a["records"] if r["error"]}
        self.assertEqual(errors,
                         {"wrong_filter", "wrong_aggregation", "wrong_join"})
        b = evaluate_system(self.conn, system_b, gold)
        self.assertEqual(b["execution_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
