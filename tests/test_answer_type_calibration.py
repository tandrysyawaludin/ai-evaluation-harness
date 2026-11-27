import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness.judge import answer_type, build_human_labels, calibrate
from evalharness.run_eval import render_report, run

ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestAnswerType(unittest.TestCase):
    def test_numeric_when_gold_states_digits(self):
        self.assertEqual(answer_type("There were 360 orders."), "numeric")
        # An account id is still digits: the answer is numeric even
        # though the headline number is what matters.
        self.assertEqual(answer_type("Account 3 placed 17 orders."),
                         "numeric")

    def test_text_when_gold_has_no_digits(self):
        self.assertEqual(
            answer_type("The symbol with the most orders was AAPL."),
            "text")
        self.assertEqual(
            answer_type("The most common order status was FILLED."), "text")

    def test_type_is_a_property_of_the_gold_answer(self):
        # A candidate written in words does not retype a numeric gold
        # answer: "twenty orders" for a 20-order gold is a numeric
        # answer, just worded. The wording blind spot is measured by
        # the disagreement patterns, not by this split.
        self.assertEqual(answer_type("Account 5 placed 20 orders."),
                         "numeric")


class TestCalibrationByAnswerType(unittest.TestCase):
    def test_splits_cover_the_label_set(self):
        result = calibrate(build_human_labels())
        by_type = result["by_answer_type"]
        self.assertEqual(set(by_type), {"numeric", "text"})
        self.assertEqual(by_type["numeric"]["n"], 44)
        self.assertEqual(by_type["text"]["n"], 4)
        self.assertEqual(by_type["numeric"]["n"] + by_type["text"]["n"],
                         result["n"])
        for t in ("numeric", "text"):
            conf = by_type[t]["confusion"]
            self.assertEqual(conf["tp"] + conf["fp"] + conf["fn"] + conf["tn"],
                             by_type[t]["n"])
        # Per-type confusion adds up to the overall confusion, so the
        # split cannot silently drop or double-count a label.
        for key in ("tp", "fp", "fn", "tn"):
            self.assertEqual(
                sum(by_type[t]["confusion"][key] for t in ("numeric", "text")),
                result["confusion"][key])

    def test_numeric_split_keeps_the_known_calibration(self):
        # The 44 numeric labels are the old set unchanged: agreement
        # 34/44, kappa 0.545. The new text labels must not move them.
        result = calibrate(build_human_labels())
        num = result["by_answer_type"]["numeric"]
        self.assertAlmostEqual(num["agreement"], 34 / 44)
        self.assertAlmostEqual(num["cohens_kappa"], 0.5454545454545454)
        self.assertEqual(num["confusion"],
                         {"tp": 17, "fp": 5, "fn": 5, "tn": 17})

    def test_text_split_shows_the_judge_is_blind_to_text(self):
        # The number-matching judge can never say "correct" to a text
        # answer: both correct text labels are false negatives, both
        # incorrect ones true negatives. Kappa 0, recall 0 — the split
        # exists to make exactly this visible.
        result = calibrate(build_human_labels())
        text = result["by_answer_type"]["text"]
        self.assertEqual(text["agreement"], 0.5)
        self.assertEqual(text["cohens_kappa"], 0.0)
        self.assertEqual(text["precision_correct"], 0.0)
        self.assertEqual(text["recall_correct"], 0.0)
        self.assertEqual(text["confusion"],
                         {"tp": 0, "fp": 0, "fn": 2, "tn": 2})

    def test_empty_labels_give_zeroed_splits(self):
        result = calibrate([])
        for t in ("numeric", "text"):
            self.assertEqual(result["by_answer_type"][t]["n"], 0)
            self.assertEqual(result["by_answer_type"][t]["cohens_kappa"], 0.0)

    def test_checked_in_labels_match_generator(self):
        with open(os.path.join(ROOT, "data", "human_labels.jsonl")) as f:
            checked = [json.loads(line) for line in f]
        self.assertEqual(len(checked), len(build_human_labels()))
        self.assertEqual(checked[-1]["gold_answer"],
                         build_human_labels()[-1]["gold_answer"])


class TestAnswerTypeSplitInReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(runs=1)

    def test_results_carry_by_answer_type(self):
        by_type = self.res["judge_calibration"]["by_answer_type"]
        self.assertEqual(by_type["numeric"]["n"], 44)
        self.assertEqual(by_type["text"]["n"], 4)
        self.assertAlmostEqual(by_type["numeric"]["cohens_kappa"], 0.545, places=3)
        self.assertEqual(by_type["text"]["cohens_kappa"], 0.0)

    def test_report_contains_answer_type_table(self):
        report = render_report(self.res)
        self.assertIn("### Calibration by answer type", report)
        self.assertIn("| numeric | 44 | 77.3% | 0.545 | 0.773 | 0.773 |",
                      report)
        self.assertIn("| text | 4 | 50.0% | 0.000 | 0.000 | 0.000 |", report)
        self.assertIn("a text gold answer can never earn a 'correct' verdict",
                      report)


if __name__ == "__main__":
    unittest.main()
