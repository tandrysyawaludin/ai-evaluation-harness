import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness import validate


def gold_item(**overrides):
    item = {"id": "q001", "question": "How many orders were placed in total?",
            "gold_sql": "SELECT COUNT(*) FROM orders",
            "category": "count_total", "difficulty": "easy"}
    item.update(overrides)
    return item


def label_item(**overrides):
    item = {"id": "h01", "gold_answer": "360 orders were placed in total.",
            "candidate_answer": "There were 360 orders in total.",
            "human_label": "correct"}
    item.update(overrides)
    return item


class TestGoldValidation(unittest.TestCase):
    def test_valid_gold_passes(self):
        self.assertEqual(validate.validate_gold([gold_item()]), [])

    def test_missing_field_reported(self):
        item = gold_item()
        del item["category"]
        errors = validate.validate_gold([item])
        self.assertTrue(any("missing required field 'category'" in e for e in errors))

    def test_unknown_field_reported(self):
        errors = validate.validate_gold([gold_item(extra="nope")])
        self.assertTrue(any("unknown field 'extra'" in e for e in errors))

    def test_duplicate_id_and_question_reported(self):
        errors = validate.validate_gold([gold_item(), gold_item()])
        self.assertTrue(any("duplicate id" in e for e in errors))
        self.assertTrue(any("duplicate question" in e for e in errors))

    def test_bad_difficulty_and_id_format(self):
        errors = validate.validate_gold(
            [gold_item(id="1", difficulty="extreme")])
        self.assertTrue(any("difficulty 'extreme'" in e for e in errors))
        self.assertTrue(any("does not match gold id format" in e for e in errors))

    def test_bad_gold_sql(self):
        for sql, fragment in [
                ("DELETE FROM orders", "start with SELECT"),
                ("SELECT COUNT(*) FROM orders; SELECT 1", "single statement"),
                ("SELECT COUNT(*)", "FROM clause"),
                ("SELECT COUNT(*) FROM mystery", "unknown table 'mystery'")]:
            errors = validate.validate_gold([gold_item(gold_sql=sql)])
            self.assertTrue(any(fragment in e for e in errors), (sql, errors))

    def test_empty_gold_is_error(self):
        self.assertEqual(validate.validate_gold([]), ["gold set is empty"])


class TestLabelValidation(unittest.TestCase):
    def test_valid_labels_pass(self):
        self.assertEqual(validate.validate_labels([label_item()]), [])

    def test_bad_human_label_and_duplicate_id(self):
        errors = validate.validate_labels(
            [label_item(human_label="maybe"), label_item()])
        self.assertTrue(any("human_label 'maybe'" in e for e in errors))
        self.assertTrue(any("duplicate id" in e for e in errors))

    def test_empty_labels_is_error(self):
        self.assertEqual(validate.validate_labels([]),
                         ["human labels are empty"])


class TestCheckedInFiles(unittest.TestCase):
    def test_checked_in_datasets_are_valid(self):
        for name, fn in (("gold.jsonl", validate.validate_gold),
                         ("human_labels.jsonl", validate.validate_labels)):
            path = os.path.join(os.path.dirname(__file__), "..", "data", name)
            items, parse_errors = validate.load_jsonl(path)
            self.assertEqual(parse_errors, [], name)
            self.assertEqual(fn(items), [], name)

    def test_malformed_json_line_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gold.jsonl")
            with open(path, "w") as f:
                f.write('{"id": "q001", broken\n')
            errors = validate.validate_file(path)
            self.assertTrue(any("invalid JSON" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
