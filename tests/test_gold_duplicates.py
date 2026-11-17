"""Near-duplicate gold questions: same normalised question or gold SQL."""
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
from evalharness.run_eval import build_gold_duplicates, render_report, run


def _gold(qid, question, sql, category="count_total", difficulty="easy"):
    return {"id": qid, "question": question, "gold_sql": sql,
            "category": category, "difficulty": difficulty}


class TestBuildGoldDuplicates(unittest.TestCase):
    def test_same_question_different_case_and_punctuation(self):
        gold = [_gold("q1", "How many orders were placed?",
                      "SELECT COUNT(*) FROM orders"),
                _gold("q2", "how many orders were placed",
                      "SELECT COUNT(*) FROM orders WHERE status = 'FILLED'")]
        d = build_gold_duplicates(gold)
        self.assertEqual(d["total_groups"], 1)
        self.assertEqual(d["groups"][0]["kind"], "question")
        self.assertEqual(d["groups"][0]["ids"], ["q1", "q2"])
        self.assertEqual(d["groups"][0]["shared"],
                         "how many orders were placed")
        self.assertEqual(d["duplicate_ids"], ["q1", "q2"])

    def test_same_sql_different_wording(self):
        gold = [_gold("q1", "How many orders in Q3 2025?",
                      "SELECT COUNT(*) FROM orders WHERE order_date "
                      "BETWEEN '2025-07-01' AND '2025-09-30'"),
                _gold("q2", "How many orders between July and September 2025?",
                      "select count(*)  from orders where order_date "
                      "between '2025-07-01' and '2025-09-30';")]
        d = build_gold_duplicates(gold)
        self.assertEqual(d["total_groups"], 1)
        self.assertEqual(d["groups"][0]["kind"], "gold_sql")
        self.assertEqual(d["groups"][0]["ids"], ["q1", "q2"])
        self.assertIn("select count(*) from orders", d["groups"][0]["shared"])

    def test_no_duplicates(self):
        gold = [_gold("q1", "How many orders?", "SELECT COUNT(*) FROM orders"),
                _gold("q2", "How many clients?", "SELECT COUNT(*) FROM clients")]
        d = build_gold_duplicates(gold)
        self.assertEqual(d, {"groups": [], "total_groups": 0,
                             "duplicate_ids": []})

    def test_different_dates_are_not_duplicates(self):
        # The numbers in a question are part of what it asks: two
        # questions over different date ranges stay distinct.
        gold = [_gold("q1", "How many orders in July 2025?",
                      "SELECT COUNT(*) FROM orders WHERE order_date "
                      "BETWEEN '2025-07-01' AND '2025-07-31'"),
                _gold("q2", "How many orders in August 2025?",
                      "SELECT COUNT(*) FROM orders WHERE order_date "
                      "BETWEEN '2025-08-01' AND '2025-08-31'")]
        self.assertEqual(build_gold_duplicates(gold)["total_groups"], 0)

    def test_group_of_three(self):
        gold = [_gold("q1", "Count the orders",
                      "SELECT COUNT(*) FROM orders"),
                _gold("q2", "count the orders!",
                      "SELECT COUNT(*) FROM orders WHERE status='FILLED'"),
                _gold("q3", "COUNT  THE  ORDERS",
                      "SELECT COUNT(*) FROM orders WHERE side='BUY'")]
        d = build_gold_duplicates(gold)
        self.assertEqual(d["total_groups"], 1)
        self.assertEqual(d["groups"][0]["ids"], ["q1", "q2", "q3"])

    def test_sql_group_dropped_when_it_matches_question_group(self):
        # Same pair, same question and same SQL: report it once, as a
        # question duplicate, not twice.
        gold = [_gold("q1", "How many orders?",
                      "SELECT COUNT(*) FROM orders"),
                _gold("q2", "how many orders",
                      "SELECT COUNT(*) FROM orders")]
        d = build_gold_duplicates(gold)
        self.assertEqual(d["total_groups"], 1)
        self.assertEqual(d["groups"][0]["kind"], "question")

    def test_sql_group_kept_when_it_extends_question_group(self):
        # q1/q2 share a question; q3 shares their SQL under different
        # wording. The SQL group still adds information (q3), so it stays.
        gold = [_gold("q1", "How many orders?",
                      "SELECT COUNT(*) FROM orders"),
                _gold("q2", "how many orders",
                      "SELECT COUNT(*) FROM orders"),
                _gold("q3", "Count all orders please",
                      "SELECT COUNT(*) FROM orders")]
        d = build_gold_duplicates(gold)
        self.assertEqual(d["total_groups"], 2)
        self.assertEqual([g["kind"] for g in d["groups"]],
                         ["question", "gold_sql"])
        self.assertEqual(d["duplicate_ids"], ["q1", "q2", "q3"])

    def test_empty_input(self):
        self.assertEqual(build_gold_duplicates([]),
                         {"groups": [], "total_groups": 0,
                          "duplicate_ids": []})


class TestRunGoldDuplicates(unittest.TestCase):
    def test_run_carries_gold_duplicates(self):
        res = run(runs=1, seed=42)
        d = res["gold_duplicates"]
        self.assertEqual(d["total_groups"], len(d["groups"]))
        self.assertEqual(d["duplicate_ids"],
                         sorted({i for g in d["groups"] for i in g["ids"]}))

    def test_real_gold_set_flags_q061_q063(self):
        # The real gold set has one genuine near-duplicate: q061 asks
        # for orders "between 2025-07-01 and 2025-09-30" and q063 for
        # orders "in the third quarter of 2025" — same gold SQL.
        res = run(runs=1, seed=42)
        d = res["gold_duplicates"]
        self.assertEqual(d["total_groups"], 1)
        self.assertEqual(d["groups"][0]["kind"], "gold_sql")
        self.assertEqual(d["groups"][0]["ids"], ["q061", "q063"])
        self.assertEqual(d["duplicate_ids"], ["q061", "q063"])

    def test_report_renders_duplicates_section(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        self.assertIn("## Gold-set near-duplicates", report)
        self.assertIn("q061, q063", report)
        self.assertIn("select count(*) from orders where order_date "
                      "between '2025-07-01' and '2025-09-30'", report)

    def test_report_without_duplicates_data_omits_section(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        del res["gold_duplicates"]
        self.assertNotIn("## Gold-set near-duplicates", render_report(res))

    def test_cli_writes_gold_duplicates_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            self.assertEqual(res["gold_duplicates"]["duplicate_ids"],
                             ["q061", "q063"])
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("## Gold-set near-duplicates", f.read())


if __name__ == "__main__":
    unittest.main()
