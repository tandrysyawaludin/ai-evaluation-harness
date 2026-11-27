import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness.judge import (DISAGREEMENT_PATTERNS,
                               build_human_labels, calibrate,
                               classify_disagreement)
from evalharness.run_eval import render_report, run

# The designed disagreement cases in build_human_labels(): the first 34
# labels agree with the judge; h35-h39 are false positives and h40-h44
# false negatives, each written to exercise one pattern. h45-h46 are
# the correct text answers: the judge says "incorrect" because there
# are no digits to match, and no named pattern explains that, so they
# are "other" — a structural blind spot, not a borderline call.
EXPECTED_PATTERNS = {
    "h35": "wrong_symbol",   # gold number for NVDA, candidate says AAPL
    "h36": "wrong_side",     # 185 SELL orders, gold counts BUY orders
    "h37": "wrong_scope",    # Account 17 placed 3 orders, gold: Account 3, 17
    "h38": "wrong_scope",    # Canada clients, gold counts Japan clients
    "h39": "wrong_metric",   # average quantity, gold asks average price
    "h40": "wording",        # "Three hundred sixty orders"
    "h41": "rounding",       # "about 1.23 million" for 1,234,500
    "h42": "wording",        # "roughly fifty-four"
    "h43": "wording",        # "two hundred shares"
    "h44": "wording",        # "twenty orders" (account id stays digits)
    "h45": "other",          # text answer: no digits for the judge to match
    "h46": "other",          # text answer: no digits for the judge to match
}


class TestClassifyDisagreement(unittest.TestCase):
    def test_designed_cases_classified_as_intended(self):
        result = calibrate(build_human_labels())
        by_id = {d["id"]: d for d in result["disagreements"]}
        self.assertEqual(set(by_id), set(EXPECTED_PATTERNS))
        for label_id, pattern in EXPECTED_PATTERNS.items():
            self.assertEqual(by_id[label_id]["pattern"], pattern, label_id)

    def test_pattern_counts_match_designed_cases(self):
        result = calibrate(build_human_labels())
        self.assertEqual(result["disagreement_patterns"], {
            "total": 12,
            "counts": {
                "wrong_symbol": 1,
                "wrong_side": 1,
                "wrong_metric": 1,
                "wrong_scope": 2,
                "wording": 4,
                "rounding": 1,
                "other": 2,
            },
        })

    def test_counts_always_sum_to_disagreement_total(self):
        result = calibrate(build_human_labels())
        counts = result["disagreement_patterns"]["counts"]
        self.assertEqual(sum(counts.values()),
                         result["disagreement_patterns"]["total"])
        self.assertEqual(result["disagreement_patterns"]["total"],
                         len(result["disagreements"]))
        for d in result["disagreements"]:
            self.assertIn(d["pattern"], DISAGREEMENT_PATTERNS)

    def test_agreement_is_not_a_disagreement(self):
        self.assertIsNone(classify_disagreement(
            "There were 360 orders.", "360 orders total.",
            "correct", "correct"))
        self.assertIsNone(classify_disagreement(
            "There were 360 orders.", "320 orders total.",
            "incorrect", "incorrect"))

    def test_unclassifiable_disagreement_is_other_not_dropped(self):
        # Same symbol, side, metric and scope, yet the human says wrong:
        # nothing in the named shapes explains it, so it is "other" and
        # still counted, rather than silently disappearing from the totals.
        self.assertEqual(classify_disagreement(
            "There were 360 orders.", "There were 360 orders in March.",
            "incorrect", "correct"), "other")
        # A wrong number that is neither a rounding nor written in words.
        self.assertEqual(classify_disagreement(
            "There were 360 orders.", "There were 180 orders.",
            "correct", "incorrect"), "other")

    def test_rounding_covers_rescaled_and_plain_forms(self):
        self.assertEqual(classify_disagreement(
            "The total was 2,500,000.", "The total was about 2.5 million.",
            "correct", "incorrect"), "rounding")
        self.assertEqual(classify_disagreement(
            "The average was 54.2.", "The average was 54.",
            "correct", "incorrect"), "rounding")
        # 1.23 for 1,234,500 is within the 1% rounding bound; 1.1 is not.
        self.assertEqual(classify_disagreement(
            "The total was 1,234,500.", "The total was 1.1 million.",
            "correct", "incorrect"), "other")


class TestDisagreementPatternsInReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(runs=1)

    def test_results_carry_pattern_summary(self):
        j = self.res["judge_calibration"]
        patterns = j["disagreement_patterns"]
        self.assertEqual(patterns["total"], len(j["disagreements"]))
        self.assertEqual(sum(patterns["counts"].values()), patterns["total"])
        for d in j["disagreements"]:
            self.assertIn(d["pattern"], DISAGREEMENT_PATTERNS)

    def test_report_contains_pattern_counts(self):
        report = render_report(self.res)
        self.assertIn("### Disagreement patterns", report)
        for pattern, count in self.res["judge_calibration"][
                "disagreement_patterns"]["counts"].items():
            self.assertIn(f"| {pattern} |", report)
            self.assertIn(f"| {count} |", report)
        for d in self.res["judge_calibration"]["disagreements"]:
            self.assertIn(f"{d['id']} ({d['pattern']})", report)


if __name__ == "__main__":
    unittest.main()
