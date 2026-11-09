"""Failures export: one CSV row per failed question, for manual review.

The report summarises failures by category, but fixing them needs the
actual questions: what was asked, what SQL the system produced, and what
the gold SQL was. This module flattens the per-system failure records
from a results dict into a CSV a human can open in a spreadsheet, sort,
and filter — without re-running the eval or digging through results.json.

One row per failed question per system, so a question both systems miss
appears twice (once per system); a system with no failures contributes
no rows, and a run with no failures at all still writes the header.
"""
import csv

FAILURE_COLUMNS = (
    "id",
    "system",
    "category",
    "difficulty",
    "question",
    "error",
    "candidate_sql",
    "gold_sql",
    "exact_match",
    "latency_ms",
)


def failure_rows(result, gold=None):
    """Failure rows for every system in `result`, sorted by system then id.

    `gold` is the list of gold items (for the question text, which the
    per-question records do not carry); without it the question column
    is empty. Records with no error are skipped.
    """
    questions = {item["id"]: item.get("question", "") for item in gold or []}
    rows = []
    for system in ("system_a", "system_b"):
        for record in result["systems"][system]["records"]:
            if not record["error"]:
                continue
            rows.append({
                "id": record["id"],
                "system": system,
                "category": record["category"],
                "difficulty": record["difficulty"],
                "question": questions.get(record["id"], ""),
                "error": record["error"],
                "candidate_sql": record["candidate_sql"],
                "gold_sql": record["gold_sql"],
                "exact_match": record["exact_match"],
                "latency_ms": record["latency_ms"],
            })
    rows.sort(key=lambda row: (row["system"], row["id"]))
    return rows


def write_failures_csv(result, path, gold=None):
    """Write the failures CSV to `path`. Returns the number of rows."""
    rows = failure_rows(result, gold)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FAILURE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
