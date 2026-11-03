"""Metrics: execution accuracy, exact match, error categorisation."""
import re
import sqlite3
import time

from .stats import latency_summary


def normalise_sql(sql):
    if not sql:
        return ""
    s = re.sub(r"\s+", " ", sql.strip().lower()).rstrip(";")
    return s


def exact_match(candidate_sql, gold_sql):
    return normalise_sql(candidate_sql) == normalise_sql(gold_sql)


def _normalise_rows(rows):
    def cell(x):
        return round(x, 4) if isinstance(x, float) else x
    return sorted(tuple(cell(c) for c in row) for row in rows)


def execute(conn, sql):
    """Return (rows, error). Rows is None on error / no SQL."""
    if not sql:
        return None, "no_sql"
    try:
        return conn.execute(sql).fetchall(), None
    except sqlite3.Error as e:
        return None, str(e)


def results_equal(conn, candidate_sql, gold_sql):
    gold_rows, gold_err = execute(conn, gold_sql)
    cand_rows, cand_err = execute(conn, candidate_sql)
    if cand_err is not None:
        return False
    if gold_err is not None:
        raise ValueError(f"gold SQL failed: {gold_err}")
    return _normalise_rows(cand_rows) == _normalise_rows(gold_rows)


def categorise_error(conn, candidate_sql, gold_sql):
    """None if correct, else one of the error categories."""
    if not candidate_sql:
        return "no_sql_generated"
    cand_rows, cand_err = execute(conn, candidate_sql)
    if cand_err is not None:
        return "execution_error"
    gold_rows, _ = execute(conn, gold_sql)
    if _normalise_rows(cand_rows) == _normalise_rows(gold_rows):
        return None
    if len(cand_rows) == 0:
        return "empty_result"
    return "wrong_result"


def evaluate_system(conn, system_fn, gold_items):
    """Run one system over the gold set. Returns per-item records + summary.

    Each record carries `latency_ms`: wall time spent inside the system
    function for that question (generation time, not SQL execution time).
    Generation is what an LLM-backed system would spend its budget on, so
    it is the latency that matters when comparing candidate systems; the
    summary reports its mean and p95.
    """
    records = []
    for item in gold_items:
        start = time.perf_counter()
        sql = system_fn(item["question"])
        latency_ms = (time.perf_counter() - start) * 1000
        err = categorise_error(conn, sql, item["gold_sql"])
        records.append({
            "id": item["id"], "category": item["category"],
            "difficulty": item["difficulty"],
            "candidate_sql": sql, "gold_sql": item["gold_sql"],
            "execution_correct": err is None,
            "exact_match": exact_match(sql, item["gold_sql"]),
            "error": err,
            "latency_ms": latency_ms,
        })
    n = len(records)
    correct = sum(r["execution_correct"] for r in records)
    return {
        "records": records,
        "n": n,
        "execution_accuracy": correct / n if n else 0.0,
        "exact_match_rate": (sum(r["exact_match"] for r in records) / n) if n else 0.0,
        "latency": latency_summary([r["latency_ms"] for r in records]),
    }
