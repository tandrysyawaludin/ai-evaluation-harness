"""Metrics: execution accuracy, exact match, error categorisation."""
import re
import sqlite3


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
    """Run one system over the gold set. Returns per-item records + summary."""
    records = []
    for item in gold_items:
        sql = system_fn(item["question"])
        err = categorise_error(conn, sql, item["gold_sql"])
        records.append({
            "id": item["id"], "category": item["category"],
            "difficulty": item["difficulty"],
            "candidate_sql": sql, "gold_sql": item["gold_sql"],
            "execution_correct": err is None,
            "exact_match": exact_match(sql, item["gold_sql"]),
            "error": err,
        })
    n = len(records)
    correct = sum(r["execution_correct"] for r in records)
    return {
        "records": records,
        "n": n,
        "execution_accuracy": correct / n if n else 0.0,
        "exact_match_rate": (sum(r["exact_match"] for r in records) / n) if n else 0.0,
    }
