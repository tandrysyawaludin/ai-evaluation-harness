"""Schema validation for the harness's JSONL datasets.

The gold set and the human labels are the ground truth everything else
is measured against, so a malformed row — a missing field, a duplicated
id, a difficulty typo, a gold SQL string that is not a single SELECT —
must fail loudly here instead of silently skewing an evaluation. The
harness runs this check before evaluating (see run_eval), and the module
is also a standalone CLI:

  PYTHONPATH=src python -m evalharness.validate
  PYTHONPATH=src python -m evalharness.validate data/gold.jsonl

Standard library only. Validators return a list of human-readable error
strings (empty means valid) rather than raising on the first problem, so
a broken file reports every problem in one pass.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

GOLD_FIELDS = {"id", "question", "gold_sql", "category", "difficulty"}
LABEL_FIELDS = {"id", "gold_answer", "candidate_answer", "human_label"}
DIFFICULTIES = {"easy", "medium", "hard"}
HUMAN_LABELS = {"correct", "incorrect"}
# Tables in the seeded brokerage database (see db.py).
KNOWN_TABLES = {"clients", "accounts", "securities", "orders", "positions"}

_GOLD_ID_RE = re.compile(r"^q\d+$")
_LABEL_ID_RE = re.compile(r"^h\d+$")
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def _check_common(item, fields, id_re, kind, where, errors):
    """Field presence, unknown fields, id shape and uniqueness."""
    if not isinstance(item, dict):
        errors.append(f"{where}: expected a JSON object, got {type(item).__name__}")
        return None
    for field in sorted(fields - set(item)):
        errors.append(f"{where}: missing required field '{field}'")
    for field in sorted(set(item) - fields):
        errors.append(f"{where}: unknown field '{field}'")
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        if not id_re.match(item_id):
            errors.append(f"{where}: id '{item_id}' does not match {kind} id format")
    elif "id" in item:
        errors.append(f"{where}: id must be a non-empty string")
    return item_id


def _check_nonempty_str(item, field, where, errors):
    value = item.get(field)
    if isinstance(value, str) and value.strip():
        return True
    if field in item:
        errors.append(f"{where}: '{field}' must be a non-empty string")
    return False


def validate_gold(items):
    """Validate a parsed gold list; return a list of error strings."""
    errors = []
    if not items:
        return ["gold set is empty"]
    seen_ids, seen_questions = set(), set()
    for i, item in enumerate(items):
        where = f"gold.jsonl:{i + 1}"
        item_id = _check_common(item, GOLD_FIELDS, _GOLD_ID_RE, "gold", where, errors)
        if not isinstance(item, dict):
            continue
        if item_id:
            where = f"{where} ({item_id})"
            if item_id in seen_ids:
                errors.append(f"{where}: duplicate id")
            seen_ids.add(item_id)
        if _check_nonempty_str(item, "question", where, errors):
            if item["question"] in seen_questions:
                errors.append(f"{where}: duplicate question text")
            seen_questions.add(item["question"])
        if _check_nonempty_str(item, "gold_sql", where, errors):
            sql = item["gold_sql"].strip()
            if ";" in sql:
                errors.append(f"{where}: gold_sql must be a single statement "
                              f"(no semicolons)")
            if not sql.upper().startswith("SELECT"):
                errors.append(f"{where}: gold_sql must start with SELECT")
            if not re.search(r"\bFROM\b", sql, re.IGNORECASE):
                errors.append(f"{where}: gold_sql must contain a FROM clause")
            for table in _TABLE_RE.findall(sql):
                if table.lower() not in KNOWN_TABLES:
                    errors.append(f"{where}: gold_sql references unknown table "
                                  f"'{table}'")
        _check_nonempty_str(item, "category", where, errors)
        difficulty = item.get("difficulty")
        if isinstance(difficulty, str) and difficulty not in DIFFICULTIES:
            errors.append(f"{where}: difficulty '{difficulty}' must be one of "
                          f"{sorted(DIFFICULTIES)}")
        elif "difficulty" in item and not isinstance(difficulty, str):
            errors.append(f"{where}: difficulty must be a string")
    return errors


def validate_labels(items):
    """Validate a parsed human-labels list; return error strings."""
    errors = []
    if not items:
        return ["human labels are empty"]
    seen_ids = set()
    for i, item in enumerate(items):
        where = f"human_labels.jsonl:{i + 1}"
        item_id = _check_common(item, LABEL_FIELDS, _LABEL_ID_RE, "label", where, errors)
        if not isinstance(item, dict):
            continue
        if item_id:
            where = f"{where} ({item_id})"
            if item_id in seen_ids:
                errors.append(f"{where}: duplicate id")
            seen_ids.add(item_id)
        _check_nonempty_str(item, "gold_answer", where, errors)
        _check_nonempty_str(item, "candidate_answer", where, errors)
        label = item.get("human_label")
        if isinstance(label, str) and label not in HUMAN_LABELS:
            errors.append(f"{where}: human_label '{label}' must be one of "
                          f"{sorted(HUMAN_LABELS)}")
        elif "human_label" in item and not isinstance(label, str):
            errors.append(f"{where}: human_label must be a string")
    return errors


def load_jsonl(path):
    """Parse a JSONL file, returning (items, parse_errors)."""
    items, errors = [], []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                errors.append(f"{os.path.basename(path)}:{i}: invalid JSON: {exc}")
    return items, errors


def validate_file(path):
    """Validate one dataset file by name; returns error strings."""
    name = os.path.basename(path)
    items, errors = load_jsonl(path)
    if name == "gold.jsonl":
        errors.extend(validate_gold(items))
    elif name == "human_labels.jsonl":
        errors.extend(validate_labels(items))
    else:
        errors.append(f"{name}: unknown dataset file "
                      f"(expected gold.jsonl or human_labels.jsonl)")
    return errors


def validate_default_files():
    """Validate the checked-in datasets; returns (path, errors) pairs."""
    return [(os.path.join(ROOT, "data", name), validate_file(
        os.path.join(ROOT, "data", name)))
        for name in ("gold.jsonl", "human_labels.jsonl")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="JSONL files to validate "
                    "(default: data/gold.jsonl and data/human_labels.jsonl)")
    args = ap.parse_args(argv)
    paths = args.files or [os.path.join(ROOT, "data", name)
                           for name in ("gold.jsonl", "human_labels.jsonl")]
    total_errors = 0
    for path in paths:
        if not os.path.exists(path):
            print(f"{path}: file not found")
            total_errors += 1
            continue
        errors = validate_file(path)
        total_errors += len(errors)
        if errors:
            for err in errors:
                print(err)
        else:
            print(f"{path}: valid")
    if total_errors:
        print(f"SCHEMA VALIDATION: FAIL ({total_errors} error(s))")
        return 1
    print("SCHEMA VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
