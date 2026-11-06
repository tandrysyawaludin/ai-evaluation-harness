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


def _where_conjuncts(sql):
    """Sorted set of top-level AND-conjuncts of the WHERE clause.

    Conjunct order does not matter (`A AND B` is the same filter as
    `B AND A`), so the clause is split and sorted before comparison.
    """
    m = re.search(r"\bwhere\b(.*?)(?:\bgroup by\b|\border by\b|\blimit\b|$)",
                  sql, re.DOTALL)
    if not m:
        return frozenset()
    clause = m.group(1)
    # Protect BETWEEN ... AND ... so its inner AND is not a conjunct split.
    protected = re.sub(r"(\bbetween\b\s+\S+\s+)\band\b(\s+\S+)",
                       r"\1@@@\2", clause)
    parts = [p.strip() for p in protected.split(" and ")]
    return frozenset(p.replace("@@@", " and ") for p in parts if p)


def _join_tables(sql):
    """Set of tables named after a JOIN keyword (empty when no join)."""
    return frozenset(re.findall(r"\bjoin\s+(\w+)", sql))


def _aggregation_signature(sql):
    """Aggregate calls plus GROUP BY, with table qualifiers stripped.

    `SUM(o.quantity * o.price)` and `SUM(quantity * price)` are the same
    aggregation written against an aliased table, so `alias.` prefixes are
    removed before comparing. The GROUP BY clause is part of the
    signature: grouping by the wrong column is an aggregation failure,
    not a filter failure.
    """
    s = re.sub(r"\b\w+\.", "", sql)
    calls = re.findall(r"\b(?:avg|sum|count|min|max)\s*\([^)]*\)", s)
    m = re.search(r"\bgroup by\b(.*?)(?:\border by\b|\blimit\b|$)", s, re.DOTALL)
    group_by = m.group(1).strip() if m else ""
    return (tuple(sorted(calls)), group_by)


def _classify_wrong_result(candidate_sql, gold_sql):
    """Split a wrong result into wrong_join / wrong_aggregation /
    wrong_filter / wrong_result, where the SQL shows which part diverged.

    Priority is deliberate: a missing join also drops the join's filter,
    so the join is checked first; an aggregation error is checked before
    the filter because a wrong aggregate changes the number even when the
    rows selected are right. Anything else stays generic wrong_result —
    e.g. a wrong SELECT column, ORDER BY, or LIMIT with the filter, join,
    and aggregation all intact.
    """
    cand, gold = normalise_sql(candidate_sql), normalise_sql(gold_sql)
    if _join_tables(cand) != _join_tables(gold):
        return "wrong_join"
    if _aggregation_signature(cand) != _aggregation_signature(gold):
        return "wrong_aggregation"
    if _where_conjuncts(cand) != _where_conjuncts(gold):
        return "wrong_filter"
    return "wrong_result"


def categorise_error(conn, candidate_sql, gold_sql):
    """None if correct, else one of the error categories.

    Categories: no_sql_generated, execution_error, empty_result,
    wrong_join, wrong_aggregation, wrong_filter, wrong_result.
    """
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
    return _classify_wrong_result(candidate_sql, gold_sql)


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
