"""Evaluation harness CLI.

Builds the seeded brokerage DB, runs both candidate systems over the gold
set (repeatedly, to measure pass-consistency under non-determinism),
computes confidence intervals and the paired McNemar test, calibrates the
judge, and writes results/results.json + results/report.md +
results/failures.csv (one row per failed question, for manual review).

By default the eval runs under two database seeds (42 and 1234) and
reports how stable the headline metrics are across them — the same
questions and systems, different database contents. Ground truth is the
gold SQL executed on each seed's data, so the comparison is fair: only
the data moves, never the questions.

Usage:  PYTHONPATH=src python -m evalharness.run_eval --runs 3
        PYTHONPATH=src python -m evalharness.run_eval --runs 3 --seeds 42 7
        PYTHONPATH=src python -m evalharness.run_eval --runs 3 --category count_by_date_range
        PYTHONPATH=src python -m evalharness.run_eval --compare old.json new.json
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict

from .compare import compare_results, render_compare
from .db import build_db
from .failures import write_failures_csv
from .judge import DISAGREEMENT_PATTERNS, calibrate
from .metrics import evaluate_system, normalise_sql
from .stats import (bootstrap_ci, bootstrap_diff_ci, mcnemar,
                    sample_size_for_difference, wilson_interval)
from .systems import SYSTEMS
from .validate import validate_gold, validate_labels

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Default seeds for the seed-sensitivity run: the long-standing primary
# seed plus one second seed. Any headline metric that moves a lot between
# them is seed noise, not a system property.
DEFAULT_SEEDS = (42, 1234)

# A headline metric is called stable when its largest swing across seeds
# is at most this many points — the same 5pp the sample-size estimator
# treats as the smallest improvement worth detecting.
STABILITY_THRESHOLD = 0.05


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def build_seed_sensitivity(per_seed):
    """Summarise headline-metric stability across per-seed results.

    `per_seed` maps a DB seed to that seed's full result dict (as returned
    by `_run_single_seed`). Returns per-seed headline numbers, the largest
    swing (max − min) of each headline metric across seeds, and whether
    every swing is within STABILITY_THRESHOLD.
    """
    per_seed_summary = {}
    for seed, res in per_seed.items():
        a, b = res["systems"]["system_a"], res["systems"]["system_b"]
        per_seed_summary[str(seed)] = {
            "system_a_accuracy": a["execution_accuracy"],
            "system_b_accuracy": b["execution_accuracy"],
            "accuracy_difference_b_minus_a": (
                res["comparison"]["accuracy_difference_b_minus_a"]),
            "system_a_correct": a["correct"],
            "system_b_correct": b["correct"],
            "n": a["n"],
            "mcnemar_p_value": res["comparison"]["mcnemar"]["p_value"],
        }

    def spread(key):
        vals = [s[key] for s in per_seed_summary.values()]
        return max(vals) - min(vals)

    spreads = {
        "system_a_accuracy": spread("system_a_accuracy"),
        "system_b_accuracy": spread("system_b_accuracy"),
        "accuracy_difference_b_minus_a": spread("accuracy_difference_b_minus_a"),
    }
    return {
        "seeds": sorted(per_seed),
        "per_seed": per_seed_summary,
        "spread": spreads,
        "stability_threshold": STABILITY_THRESHOLD,
        "stable": all(v <= STABILITY_THRESHOLD for v in spreads.values()),
    }


def build_win_loss(records_a, records_b):
    """Per-question win/loss table for the paired system comparison.

    Each question is one of four outcomes: both systems correct, both
    wrong, only A correct, or only B correct. The two discordant counts
    are exactly McNemar's b (A wrong, B right) and c (A right, B wrong),
    so this table is the auditable detail behind the test — it names the
    questions, not just the counts. Rows are ordered with the discordant
    questions first (B wins, then A wins), then both-wrong, then
    both-correct, each group sorted by question id.
    """
    if len(records_a) != len(records_b):
        raise ValueError(
            "cannot build win/loss table: record counts differ "
            f"({len(records_a)} vs {len(records_b)})")
    outcome_order = {"b_only": 0, "a_only": 1, "both_wrong": 2, "both_correct": 3}
    rows = []
    for ra, rb in zip(records_a, records_b):
        if ra["id"] != rb["id"]:
            raise ValueError(
                "cannot build win/loss table: record ids misaligned "
                f"({ra['id']} vs {rb['id']})")
        a_ok, b_ok = ra["execution_correct"], rb["execution_correct"]
        if a_ok and b_ok:
            outcome = "both_correct"
        elif not a_ok and not b_ok:
            outcome = "both_wrong"
        elif b_ok:
            outcome = "b_only"
        else:
            outcome = "a_only"
        rows.append({
            "id": ra["id"],
            "category": ra["category"],
            "difficulty": ra["difficulty"],
            "system_a_correct": a_ok,
            "system_b_correct": b_ok,
            "outcome": outcome,
        })
    rows.sort(key=lambda r: (outcome_order[r["outcome"]], r["id"]))
    counts = {k: sum(1 for r in rows if r["outcome"] == k)
              for k in outcome_order}
    return {"n": len(rows), "counts": counts, "rows": rows}


def build_split_half(gold, records_a, records_b):
    """Split-half reliability: per-system accuracy on each half of the
    gold set.

    The halves are interleaved by position (even-indexed questions in
    half 1, odd-indexed in half 2), not cut in the middle: gold.jsonl
    is grouped by category, so a contiguous cut would make the halves
    differ by category and conflate category difficulty with half
    difference. Interleaving keeps both halves spanning the whole set,
    so a gap between halves means the headline accuracy leans on one
    half of the questions, not on one kind of question.

    Returns per-half n and per-system accuracy, the B − A gap per half,
    and the largest half-to-half accuracy gap per system. A system is
    called balanced when its two halves agree within 5pp — the same
    smallest-difference threshold the sample-size estimator uses.
    """
    if len(records_a) != len(records_b) or len(records_a) != len(gold):
        raise ValueError(
            "cannot build split-half reliability: gold and record "
            f"counts differ ({len(gold)} gold, {len(records_a)} system_a, "
            f"{len(records_b)} system_b)")
    for item, ra, rb in zip(gold, records_a, records_b):
        if ra["id"] != item["id"] or rb["id"] != item["id"]:
            raise ValueError(
                "cannot build split-half reliability: record ids "
                f"misaligned with gold ({item['id']} vs {ra['id']} / "
                f"{rb['id']})")
    halves = {}
    for half, indices in (("half_1", range(0, len(gold), 2)),
                          ("half_2", range(1, len(gold), 2))):
        indices = list(indices)
        n = len(indices)
        a_correct = sum(1 for i in indices if records_a[i]["execution_correct"])
        b_correct = sum(1 for i in indices if records_b[i]["execution_correct"])
        halves[half] = {
            "n": n,
            "system_a_correct": a_correct,
            "system_b_correct": b_correct,
            "system_a_accuracy": a_correct / n if n else 0.0,
            "system_b_accuracy": b_correct / n if n else 0.0,
            "accuracy_difference_b_minus_a": (
                (b_correct - a_correct) / n if n else 0.0),
        }
    gaps = {
        "system_a": abs(halves["half_1"]["system_a_accuracy"]
                        - halves["half_2"]["system_a_accuracy"]),
        "system_b": abs(halves["half_1"]["system_b_accuracy"]
                        - halves["half_2"]["system_b_accuracy"]),
        "accuracy_difference_b_minus_a": abs(
            halves["half_1"]["accuracy_difference_b_minus_a"]
            - halves["half_2"]["accuracy_difference_b_minus_a"]),
    }
    return {
        "halves": halves,
        "gap": gaps,
        "balance_threshold": 0.05,
        "balanced": all(v <= 0.05 for v in gaps.values()),
    }


def build_flaky_questions(gold, per_question_correct, runs):
    """Questions correct on some repeated runs but not all.

    `per_question_correct[i]` counts how many of the `runs` repeated
    evaluations got gold[i] right. A question with 0 < count < runs is
    flaky: its contribution to the headline accuracy is luck, not
    capability. For a deterministic system the list is empty, which is
    itself the finding — the system is deterministic on this gold set.
    Rows are ordered least-consistent first, so the questions closest
    to a coin flip lead.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if len(gold) != len(per_question_correct):
        raise ValueError(
            "cannot build flaky-question report: gold size and "
            f"per-question counts differ ({len(gold)} vs "
            f"{len(per_question_correct)})")
    rows = []
    for item, count in zip(gold, per_question_correct):
        if 0 < count < runs:
            rows.append({
                "id": item["id"],
                "category": item["category"],
                "difficulty": item["difficulty"],
                "correct_runs": count,
                "runs": runs,
                "fraction_correct": count / runs,
            })
    rows.sort(key=lambda r: (r["fraction_correct"], r["id"]))
    return {"runs": runs, "flaky_count": len(rows), "questions": rows}


# The fixed error taxonomy from metrics.categorise_error, in the order
# its docstring lists them: a missing answer, a crash, an empty answer,
# then the wrong-result split (join / aggregation / filter / generic).
ERROR_TYPES = ("no_sql_generated", "execution_error", "empty_result",
               "wrong_join", "wrong_aggregation", "wrong_filter",
               "wrong_result")


def _cross_tab_for_records(records):
    """One system's error-type × category cross-tab.

    `cells[category][error]` counts that system's failures of that
    error type in that category; every category × error cell exists,
    even when zero, so a column that is all zeros says that error
    never happens anywhere. `dominant_error[category]` is the error
    type with the most failures in that category — the failure mode to
    fix first for that kind of question — or None when the category
    has no failures; ties break in ERROR_TYPES order, so the result
    is deterministic.
    """
    categories = sorted({r["category"] for r in records})
    cells = {cat: {err: 0 for err in ERROR_TYPES} for cat in categories}
    for r in records:
        if r["error"]:
            cells[r["category"]][r["error"]] += 1
    category_totals = {cat: sum(cells[cat].values()) for cat in categories}
    error_totals = {err: sum(cells[cat][err] for cat in categories)
                    for err in ERROR_TYPES}
    dominant = {}
    for cat in categories:
        if category_totals[cat] == 0:
            dominant[cat] = None
        else:
            dominant[cat] = max(ERROR_TYPES,
                                key=lambda e: cells[cat][e])
    return {
        "cells": cells,
        "category_totals": category_totals,
        "error_totals": error_totals,
        "total_errors": sum(category_totals.values()),
        "dominant_error": dominant,
    }


def build_error_cross_tab(records_a, records_b):
    """Error-type × category cross-tab for both systems.

    The per-category / per-difficulty tables say *where* a system is
    weak; this says *how* it is weak there — whether a category's
    failures are mostly wrong filters, wrong joins, wrong aggregations,
    or something else. A failure mode that clusters in one kind of
    question points at one fix; the same error spread evenly across
    categories points at a general weakness instead.
    """
    if len(records_a) != len(records_b):
        raise ValueError(
            "cannot build error cross-tab: record counts differ "
            f"({len(records_a)} vs {len(records_b)})")
    for ra, rb in zip(records_a, records_b):
        if ra["id"] != rb["id"]:
            raise ValueError(
                "cannot build error cross-tab: record ids misaligned "
                f"({ra['id']} vs {rb['id']})")
    categories = sorted({r["category"] for r in records_a}
                        | {r["category"] for r in records_b})
    return {
        "categories": categories,
        "error_types": list(ERROR_TYPES),
        "systems": {
            "system_a": _cross_tab_for_records(records_a),
            "system_b": _cross_tab_for_records(records_b),
        },
    }


def build_coverage_matrix(gold, thin_threshold=3):
    """Category × difficulty coverage of the gold set.

    Every observed category is crossed with every observed difficulty,
    so a category that never tests a difficulty shows up as an empty
    cell rather than silently disappearing. A cell with fewer than
    `thin_threshold` questions is thin: its per-category / per-difficulty
    accuracy rests on too few questions to mean much, and growing the
    gold set should start there. Difficulties order easy → medium →
    hard; any unexpected value sorts after those, alphabetically.
    """
    difficulty_order = {"easy": 0, "medium": 1, "hard": 2}
    categories = sorted({item["category"] for item in gold})
    difficulties = sorted({item["difficulty"] for item in gold},
                          key=lambda d: (difficulty_order.get(d, 99), d))
    cells = {cat: {diff: 0 for diff in difficulties} for cat in categories}
    for item in gold:
        cells[item["category"]][item["difficulty"]] += 1
    empty_cells = [{"category": cat, "difficulty": diff}
                   for cat in categories for diff in difficulties
                   if cells[cat][diff] == 0]
    thin_cells = [{"category": cat, "difficulty": diff,
                   "count": cells[cat][diff]}
                  for cat in categories for diff in difficulties
                  if 0 < cells[cat][diff] < thin_threshold]
    return {
        "thin_threshold": thin_threshold,
        "categories": categories,
        "difficulties": difficulties,
        "cells": cells,
        "total_cells": len(categories) * len(difficulties),
        "empty_cells": empty_cells,
        "thin_cells": thin_cells,
    }


def _normalise_question(question):
    """Question text with case, punctuation and whitespace ignored.

    "How many orders?" and "how many orders" are the same question
    typed twice; the normalisation makes that visible. Numbers and
    dates survive (they are part of what the question asks), so two
    questions over different date ranges stay distinct.
    """
    s = re.sub(r"[^\w\s]", "", (question or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def build_gold_duplicates(gold):
    """Groups of gold questions that measure the same thing twice.

    Two items are near-duplicates when they share a normalised
    question (see `_normalise_question`) or the same normalised gold
    SQL (see `metrics.normalise_sql`). Exact duplicate question text
    is already a schema error in `validate_gold`; this catches the
    cases that slip past it — the same question retyped with different
    punctuation, and two differently worded questions with identical
    gold SQL (a paraphrase, or an accidental repeat).

    A gold-SQL group whose id set exactly matches a question group is
    dropped: the same pair reported twice adds noise, not information.
    Returns {"groups": [...], "total_groups": n, "duplicate_ids": [...]}.
    """
    def groups_for(field, normalise, kind):
        seen = {}
        for item in gold:
            key = normalise(item.get(field, ""))
            if key:
                seen.setdefault(key, []).append(item["id"])
        return [{"kind": kind, "ids": ids, "shared": key}
                for key, ids in seen.items() if len(ids) > 1]

    q_groups = groups_for("question", _normalise_question, "question")
    sql_groups = groups_for("gold_sql", normalise_sql, "gold_sql")
    q_id_sets = {frozenset(g["ids"]) for g in q_groups}
    sql_groups = [g for g in sql_groups
                  if frozenset(g["ids"]) not in q_id_sets]
    groups = sorted(q_groups + sql_groups, key=lambda g: g["ids"])
    return {
        "groups": groups,
        "total_groups": len(groups),
        "duplicate_ids": sorted({i for g in groups for i in g["ids"]}),
    }


def build_difficulty_monotonicity(per_difficulty):
    """Check accuracy falls easy -> medium -> hard, per system.

    `per_difficulty` is the per-difficulty breakdown built in
    `_run_single_seed` (accuracy and n per difficulty per system).
    Only the known ladder easy / medium / hard is checked, in that
    order, and only the difficulties actually present: a missing
    difficulty is skipped, so a gold set with no medium questions
    compares easy against hard directly. Any other difficulty label
    has no place in the ladder and is ignored. Adjacent pairs are
    enough — any inversion in the ladder implies an adjacent one.

    A violation is a harder difficulty scored *above* an easier one.
    That is a warning, not a failure: it usually means the difficulty
    labels are wrong for those questions, or the system has a blind
    spot on the "easier" kind — often a small-n cell, which is why
    each violation carries both n's so the reader can judge whether
    the gap is a handful of questions or a real pattern.
    """
    ladder = ["easy", "medium", "hard"]
    present = [d for d in ladder if d in per_difficulty]
    systems = {}
    for name in ("system_a", "system_b"):
        violations = []
        for easier, harder in zip(present, present[1:]):
            acc_easier = per_difficulty[easier][f"{name}_accuracy"]
            acc_harder = per_difficulty[harder][f"{name}_accuracy"]
            if acc_harder > acc_easier:
                violations.append({
                    "easier": easier,
                    "harder": harder,
                    "easier_accuracy": acc_easier,
                    "harder_accuracy": acc_harder,
                    "easier_n": per_difficulty[easier]["n"],
                    "harder_n": per_difficulty[harder]["n"],
                    "gap": acc_harder - acc_easier,
                })
        systems[name] = {
            "monotonic": not violations,
            "violations": violations,
        }
    return {
        "difficulties": present,
        "systems": systems,
        "monotonic": all(s["monotonic"] for s in systems.values()),
    }


def build_per_category(gold, records_a, records_b):
    """Per-category accuracy with a Wilson 95% CI per system, plus a
    paired bootstrap 95% CI for the B − A accuracy difference.

    The CI is the point of this table: a category's headline
    percentage alone overstates how much is known when the category
    holds only a handful of questions — 100% on n=4 has a Wilson
    interval roughly [0.40, 1.00], which says almost nothing. The
    interval is computed from the same counts as the accuracy, so
    the two can never disagree. Categories sort alphabetically;
    records must align with gold by id, as in build_split_half.

    The per-category difference CI is the paired version of the
    headline difference CI in `comparison`: the two systems answer
    the same questions, so the paired interval on the per-question
    differences is narrower than the two Wilson intervals would
    suggest, and an interval that excludes 0 is evidence B really is
    better (or worse) than A *in that category*, not just overall.
    Each category's bootstrap uses a deterministic seed (123 plus
    its position in the sorted category order), so repeated runs
    reproduce the same interval.
    """
    if len(records_a) != len(records_b) or len(records_a) != len(gold):
        raise ValueError(
            "cannot build per-category breakdown: gold and record "
            f"counts differ ({len(gold)} gold, {len(records_a)} system_a, "
            f"{len(records_b)} system_b)")
    for item, ra, rb in zip(gold, records_a, records_b):
        if ra["id"] != item["id"] or rb["id"] != item["id"]:
            raise ValueError(
                "cannot build per-category breakdown: record ids "
                f"misaligned with gold ({item['id']} vs {ra['id']} / "
                f"{rb['id']})")
    by_cat = defaultdict(lambda: {"n": 0, "a": 0, "b": 0, "a_flags": [],
                                  "b_flags": []})
    for item, ra, rb in zip(gold, records_a, records_b):
        c = by_cat[item["category"]]
        c["n"] += 1
        c["a"] += int(ra["execution_correct"])
        c["b"] += int(rb["execution_correct"])
        c["a_flags"].append(int(ra["execution_correct"]))
        c["b_flags"].append(int(rb["execution_correct"]))
    out = {}
    for i, (cat, v) in enumerate(sorted(by_cat.items())):
        diff_ci = bootstrap_diff_ci(v["a_flags"], v["b_flags"],
                                    seed=123 + i)
        out[cat] = {"n": v["n"],
                    "system_a_correct": v["a"],
                    "system_b_correct": v["b"],
                    "system_a_accuracy": v["a"] / v["n"],
                    "system_b_accuracy": v["b"] / v["n"],
                    "system_a_wilson_95ci": wilson_interval(v["a"], v["n"]),
                    "system_b_wilson_95ci": wilson_interval(v["b"], v["n"]),
                    "difference_b_minus_a": (v["b"] - v["a"]) / v["n"],
                    "difference_bootstrap_95ci": diff_ci}
    return out


def build_per_difficulty(gold, records_a, records_b):
    """Per-difficulty accuracy with a Wilson 95% CI per system.

    Same argument as the per-category table, which already carries
    CIs: a difficulty's headline percentage overstates how much is
    known when the difficulty holds only a handful of questions —
    100% on hard n=4 has a Wilson interval roughly [0.40, 1.00].
    Difficulties order easy -> medium -> hard; any unexpected value
    sorts after those, alphabetically, rather than crashing the
    report. Records must align with gold by id, as in
    build_per_category.
    """
    if len(records_a) != len(records_b) or len(records_a) != len(gold):
        raise ValueError(
            "cannot build per-difficulty breakdown: gold and record "
            f"counts differ ({len(gold)} gold, {len(records_a)} system_a, "
            f"{len(records_b)} system_b)")
    for item, ra, rb in zip(gold, records_a, records_b):
        if ra["id"] != item["id"] or rb["id"] != item["id"]:
            raise ValueError(
                "cannot build per-difficulty breakdown: record ids "
                f"misaligned with gold ({item['id']} vs {ra['id']} / "
                f"{rb['id']})")
    difficulty_order = {"easy": 0, "medium": 1, "hard": 2}
    by_diff = defaultdict(lambda: {"n": 0, "a": 0, "b": 0})
    for item, ra, rb in zip(gold, records_a, records_b):
        d = by_diff[item["difficulty"]]
        d["n"] += 1
        d["a"] += int(ra["execution_correct"])
        d["b"] += int(rb["execution_correct"])
    return {diff: {"n": v["n"],
                   "system_a_correct": v["a"],
                   "system_b_correct": v["b"],
                   "system_a_accuracy": v["a"] / v["n"],
                   "system_b_accuracy": v["b"] / v["n"],
                   "system_a_wilson_95ci": wilson_interval(v["a"], v["n"]),
                   "system_b_wilson_95ci": wilson_interval(v["b"], v["n"])}
            for diff, v in sorted(
                by_diff.items(),
                key=lambda kv: (difficulty_order.get(kv[0], 99), kv[0]))}


def build_stratified_accuracy(per_difficulty):
    """Stratified headline accuracy: equal-weight mean of the
    per-difficulty accuracies, per system.

    The headline accuracy weights every question equally, so a gold
    set heavy in easy questions inflates it — easy questions carry
    the headline. The stratified accuracy weights every difficulty
    equally instead: it is the plain mean of the per-difficulty
    accuracies, so a difficulty's share of the headline is 1 / (number
    of difficulties), not its share of the questions. A system that is
    strong only on easy questions scores lower here than in the
    headline; a system equally strong everywhere scores the same.

    `per_difficulty` is the breakdown built by build_per_difficulty;
    every difficulty present is averaged, in the breakdown's order.
    Returns the difficulties averaged over, the stratified accuracy
    per system, and the stratified B − A difference. An empty
    breakdown stratifies to 0.0 for both systems.
    """
    difficulties = list(per_difficulty)

    def strat(name):
        if not difficulties:
            return 0.0
        return sum(per_difficulty[d][f"{name}_accuracy"]
                   for d in difficulties) / len(difficulties)

    a = strat("system_a")
    b = strat("system_b")
    return {
        "difficulties": difficulties,
        "system_a_stratified_accuracy": a,
        "system_b_stratified_accuracy": b,
        "stratified_difference_b_minus_a": b - a,
    }


def _git_output(args, cwd):
    """Stdout of a read-only git command, or None when git fails.

    Git is missing, `cwd` is not a checkout, or the command errors —
    provenance degrades to "unknown" instead of crashing the eval.
    A missing git binary and a timeout are the same kind of failure
    here, so both return None.
    """
    try:
        proc = subprocess.run(["git", "-C", cwd] + args,
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def build_provenance(gold_path, repo_root=ROOT):
    """Provenance for one eval run: what gold set and what code.

    `gold_sha256` is the SHA-256 of the raw bytes of the gold file, so
    any edit to a question, an answer, or even a trailing newline
    changes it — a results file can be matched to the exact gold set
    that produced it. `harness_commit` is the git HEAD the harness
    ran from; `harness_dirty` says whether the working tree had
    uncommitted changes at that moment, because a commit hash alone
    does not identify code that was edited after the commit. Both
    git fields are None when the repo is not a git checkout (or git
    is unavailable), so provenance degrades instead of failing.
    """
    with open(gold_path, "rb") as f:
        gold_sha256 = hashlib.sha256(f.read()).hexdigest()
    commit = _git_output(["rev-parse", "HEAD"], repo_root)
    status = _git_output(["status", "--porcelain"], repo_root)
    return {
        "gold_path": os.path.relpath(gold_path, repo_root),
        "gold_sha256": gold_sha256,
        "harness_commit": commit,
        "harness_dirty": bool(status) if status is not None else None,
    }


def _run_single_seed(runs, seed, gold, calibrate_judge=True):
    """Full evaluation under one DB seed. Judge calibration is
    seed-independent (it grades human labels, not DB rows), so only the
    primary seed computes it; extra seeds get judge_calibration=None."""
    conn = build_db(seed=seed)

    per_system = {}
    correctness = {}
    for name, fn in SYSTEMS.items():
        result = evaluate_system(conn, fn, gold)
        correct_flags = [r["execution_correct"] for r in result["records"]]
        correctness[name] = correct_flags

        # Repeated-run stability: each question attempted `runs` times.
        per_question_correct = [0] * len(gold)
        for _ in range(runs):
            again = evaluate_system(conn, fn, gold)
            for i, r in enumerate(again["records"]):
                per_question_correct[i] += int(r["execution_correct"])
        frac = [c / runs for c in per_question_correct]

        n, k = result["n"], sum(correct_flags)
        per_system[name] = {
            "n": n,
            "correct": k,
            "execution_accuracy": result["execution_accuracy"],
            "wilson_95ci": wilson_interval(k, n),
            "bootstrap_95ci": bootstrap_ci([int(x) for x in correct_flags]),
            "exact_match_rate": result["exact_match_rate"],
            # Latencies are from the first (recorded) pass only; the
            # repeated runs measure pass-consistency, not timing.
            "latency": result["latency"],
            "pass_consistency_mean": sum(frac) / len(frac) if frac else 0.0,
            "questions_correct_on_every_run": (
                sum(1 for c in per_question_correct if c == runs) / len(gold)),
            "flaky_questions": build_flaky_questions(
                gold, per_question_correct, runs),
            "error_counts": dict(Counter(
                r["error"] for r in result["records"] if r["error"])),
            "records": result["records"],
        }

    a_flags, b_flags = correctness["system_a"], correctness["system_b"]
    mc = mcnemar(a_flags, b_flags)
    diff_ci = bootstrap_diff_ci(a_flags, b_flags)

    # Per-category breakdown, with a Wilson 95% CI per system: a
    # category's headline percentage alone overstates how much is
    # known when the category holds only a handful of questions.
    categories = build_per_category(
        gold, per_system["system_a"]["records"],
        per_system["system_b"]["records"])

    # Per-difficulty breakdown (easy / medium / hard), with a Wilson
    # 95% CI per system: the same reason as the per-category table —
    # a difficulty's headline percentage alone overstates how much is
    # known when the difficulty holds only a handful of questions.
    difficulties = build_per_difficulty(
        gold, per_system["system_a"]["records"],
        per_system["system_b"]["records"])

    # Stratified headline accuracy: the plain mean of the per-difficulty
    # accuracies, so a gold set heavy in easy questions cannot inflate
    # the headline by volume alone.
    stratified = build_stratified_accuracy(difficulties)

    errors_a = [r for r in per_system["system_a"]["records"] if r["error"]]

    judge_result = None
    if calibrate_judge:
        labels_path = os.path.join(ROOT, "data", "human_labels.jsonl")
        if os.path.exists(labels_path):
            labels = load_jsonl(labels_path)
            label_errors = validate_labels(labels)
            if label_errors:
                raise ValueError("human_labels.jsonl failed schema validation:\n"
                                 + "\n".join(label_errors))
            judge_result = calibrate(labels)
            judge_result["disagreements"] = [
                {k: d[k] for k in ("id", "gold_answer", "candidate_answer",
                                   "human_label", "judge_label", "pattern")}
                for d in judge_result["disagreements"]]

    try:
        n_needed = sample_size_for_difference(
            per_system["system_a"]["execution_accuracy"], 0.05)
    except ValueError:
        n_needed = None

    return {
        "gold_size": len(gold),
        "runs_per_system": runs,
        "db_seed": seed,
        "systems": per_system,
        "comparison": {
            "accuracy_difference_b_minus_a": (
                per_system["system_b"]["execution_accuracy"]
                - per_system["system_a"]["execution_accuracy"]),
            "difference_bootstrap_95ci": diff_ci,
            "mcnemar": mc,
            "win_loss": build_win_loss(
                per_system["system_a"]["records"],
                per_system["system_b"]["records"]),
            "sample_size_to_detect_5pp_from_a": n_needed,
        },
        "per_category": categories,
        "per_difficulty": difficulties,
        "stratified_accuracy": stratified,
        "difficulty_monotonicity": build_difficulty_monotonicity(difficulties),
        "coverage_matrix": build_coverage_matrix(gold),
        "gold_duplicates": build_gold_duplicates(gold),
        "split_half": build_split_half(
            gold, per_system["system_a"]["records"],
            per_system["system_b"]["records"]),
        "error_cross_tab": build_error_cross_tab(
            per_system["system_a"]["records"],
            per_system["system_b"]["records"]),
        "system_a_errors": errors_a,
        "judge_calibration": judge_result,
    }


def filter_gold_by_category(gold, categories):
    """Restrict the gold set to the named categories.

    `categories` is a list of category names (an empty list or None
    means no filtering). A name that matches no gold question is an
    error, not an empty run: a typo in `--category` should fail loudly
    instead of producing a report over zero questions. Returns the
    filtered gold list, in the original order.
    """
    if not categories:
        return gold
    available = sorted({item["category"] for item in gold})
    unknown = sorted(set(categories) - set(available))
    if unknown:
        raise ValueError(
            "unknown categor" + ("y" if len(unknown) == 1 else "ies") + ": "
            + ", ".join(unknown) + ". Available categories: "
            + ", ".join(available))
    wanted = set(categories)
    return [item for item in gold if item["category"] in wanted]


def run(runs=3, seed=42, seeds=None, categories=None):
    """Evaluate under one or more DB seeds.

    `seeds` wins over `seed` when given; otherwise `seed` alone is used,
    so `run(runs=1)` keeps its old single-seed behaviour. The first seed
    is the primary one: its full results are the top-level `systems`
    block, so the regression gate and `--compare` keep working unchanged.
    With more than one seed the result also carries `db_seeds` and a
    `seed_sensitivity` summary of headline-metric stability.

    `categories` restricts the gold set to the named categories, for
    targeted iteration on one kind of question (e.g. date ranges).
    The result records the filter and the full gold-set size, so a
    filtered results.json is never mistaken for a full run — and the
    regression gate must only be run against unfiltered results,
    because a subset's accuracy is not comparable to the full-set
    baseline.
    """
    if seeds is None:
        seeds = (seed,)
    seeds = tuple(seeds)
    if not seeds:
        raise ValueError("at least one DB seed is required")
    gold_path = os.path.join(ROOT, "data", "gold.jsonl")
    gold = load_jsonl(gold_path)
    # Fail fast on a broken ground truth: a malformed gold row would
    # otherwise silently skew every metric the harness reports.
    gold_errors = validate_gold(gold)
    if gold_errors:
        raise ValueError("gold.jsonl failed schema validation:\n"
                         + "\n".join(gold_errors))
    gold_total = len(gold)
    gold = filter_gold_by_category(gold, categories)
    provenance = build_provenance(gold_path)

    per_seed = {}
    for i, s in enumerate(seeds):
        per_seed[s] = _run_single_seed(runs, s, gold, calibrate_judge=(i == 0))

    primary = per_seed[seeds[0]]
    # Provenance is seed-independent (same gold set, same code), so it
    # is recorded once, on the primary result.
    primary["provenance"] = provenance
    primary["db_seeds"] = list(seeds)
    primary["category_filter"] = sorted(categories) if categories else None
    primary["gold_total"] = gold_total
    primary["seed_sensitivity"] = (
        build_seed_sensitivity(per_seed) if len(seeds) > 1 else None)
    return primary


def _wilson_cell(ci):
    """Render a Wilson CI as [lo, hi]; "—" when a results file predates
    the per-category CIs, so old results still render."""
    if not ci:
        return "—"
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def render_report(res, failures_csv=None):
    a, b = res["systems"]["system_a"], res["systems"]["system_b"]
    cmp_ = res["comparison"]
    j = res["judge_calibration"]
    L = []
    L.append("# Evaluation Report — Brokerage Text-to-SQL Agent\n")
    prov = res.get("provenance")
    if prov:
        commit = prov.get("harness_commit")
        commit_text = (f"`{commit}`" if commit
                       else "unknown (not a git checkout)")
        dirty = prov.get("harness_dirty")
        tree = (" — ⚠ working tree had uncommitted changes" if dirty else
                " — clean working tree" if dirty is False else
                " — working-tree state unknown")
        L.append(f"Provenance: gold set `{prov.get('gold_path', 'data/gold.jsonl')}` "
                 f"SHA-256 `{prov['gold_sha256']}` · harness commit "
                 f"{commit_text}{tree}\n")
    L.append(f"Gold set: **{res['gold_size']} questions** · DB seed: {res['db_seed']} · "
             f"Runs per system: {res['runs_per_system']}\n")
    category_filter = res.get("category_filter")
    if category_filter:
        total = res.get("gold_total", res["gold_size"])
        L.append(f"Filtered to {len(category_filter)} "
                 f"{'category' if len(category_filter) == 1 else 'categories'} "
                 f"({', '.join(category_filter)}): {res['gold_size']} of "
                 f"{total} gold questions. Headline numbers here are for "
                 f"that subset only — compare them against a run on the "
                 f"same subset, not against the full-set baseline.\n")
    L.append("## Headline results\n")
    L.append("| System | Execution accuracy | 95% Wilson CI | 95% bootstrap CI | Exact match | Pass-consistency |")
    L.append("|---|---|---|---|---|---|")
    for name, s in (("system_a (baseline)", a), ("system_b (improved)", b)):
        L.append(f"| {name} | {s['execution_accuracy']:.1%} ({s['correct']}/{s['n']}) "
                 f"| [{s['wilson_95ci'][0]:.3f}, {s['wilson_95ci'][1]:.3f}] "
                 f"| [{s['bootstrap_95ci'][0]:.3f}, {s['bootstrap_95ci'][1]:.3f}] "
                 f"| {s['exact_match_rate']:.1%} | {s['pass_consistency_mean']:.3f} |")
    L.append("")
    strat = res.get("stratified_accuracy")
    if strat:
        L.append("## Stratified headline accuracy\n")
        diffs = res.get("per_difficulty", {})
        counts = ", ".join(
            f"{d} n={diffs[d]['n']}" for d in strat["difficulties"]
            if d in diffs)
        L.append("The headline accuracy above weights every question "
                 "equally, so a gold set heavy in easy questions inflates "
                 f"it — this set has {counts}. The stratified accuracy "
                 "weights every difficulty equally instead: it is the "
                 "plain mean of the per-difficulty accuracies, so no "
                 "difficulty can dominate the headline by volume alone. "
                 "A system that is strong only where the questions are "
                 "most numerous scores lower here than in the headline; "
                 "a system equally strong everywhere scores the same.\n")
        L.append("| System | Overall accuracy | Stratified accuracy | Inflation (overall − stratified) |")
        L.append("|---|---|---|---|")
        for name, s in (("system_a", a), ("system_b", b)):
            sa = strat[f"{name}_stratified_accuracy"]
            infl = s["execution_accuracy"] - sa
            L.append(f"| {name} | {s['execution_accuracy']:.1%} "
                     f"({s['correct']}/{s['n']}) | {sa:.1%} | {infl:+.1%} |")
        L.append("")
        L.append(f"The stratified B − A difference is "
                 f"{strat['stratified_difference_b_minus_a']:+.1%}, against "
                 f"{cmp_['accuracy_difference_b_minus_a']:+.1%} overall. "
                 f"When the two disagree, the stratified number is the one "
                 f"that survives rebalancing the gold set.")
        L.append("")
    L.append("## Is the improvement real? (paired comparison)\n")
    L.append(f"- Accuracy difference (B − A): **{cmp_['accuracy_difference_b_minus_a']:+.1%}**, "
             f"bootstrap 95% CI [{cmp_['difference_bootstrap_95ci'][0]:+.3f}, "
             f"{cmp_['difference_bootstrap_95ci'][1]:+.3f}]")
    mc = cmp_["mcnemar"]
    L.append(f"- McNemar's test (paired, same questions): b = {mc['b']} (A wrong, B right), "
             f"c = {mc['c']} (A right, B wrong), p = {mc['p_value']:.4g}")
    verdict = ("statistically significant at the 5% level"
               if mc["p_value"] < 0.05 else "not significant at the 5% level")
    L.append(f"- Verdict: the difference is **{verdict}**.")
    if cmp_["sample_size_to_detect_5pp_from_a"]:
        L.append(f"- To detect a further 5pp improvement over system_a with 80% power "
                 f"would need ~{cmp_['sample_size_to_detect_5pp_from_a']} gold questions per system "
                 f"(normal approximation) — a concrete argument for growing the gold set.")
    L.append("")
    wl = cmp_.get("win_loss")
    if wl:
        outcome_label = {"b_only": "B wins", "a_only": "A wins",
                         "both_correct": "Both correct", "both_wrong": "Both wrong"}
        c = wl["counts"]
        L.append("## Per-question win/loss (paired comparison)\n")
        L.append(f"Every question, one row: {c['both_correct']} both correct, "
                 f"{c['both_wrong']} both wrong, {c['b_only']} B only "
                 f"(McNemar b), {c['a_only']} A only (McNemar c). "
                 f"Discordant questions come first — they are the whole "
                 f"paired difference; the rest is agreement.\n")
        L.append("| ID | Category | Difficulty | system_a | system_b | Outcome |")
        L.append("|---|---|---|---|---|---|")
        for r in wl["rows"]:
            L.append(f"| {r['id']} | {r['category']} | {r['difficulty']} | "
                     f"{'✓' if r['system_a_correct'] else '✗'} | "
                     f"{'✓' if r['system_b_correct'] else '✗'} | "
                     f"{outcome_label[r['outcome']]} |")
        L.append("")
    sens = res.get("seed_sensitivity")
    if sens:
        L.append("## Seed sensitivity\n")
        L.append(f"Same systems, same {res['gold_size']} questions, re-evaluated on "
                 f"{len(sens['seeds'])} database seeds "
                 f"({', '.join(str(s) for s in sens['seeds'])}). The gold SQL is "
                 f"re-executed on each seed's data, so the ground truth moves with "
                 f"the data — what varies is only the database contents, never the "
                 f"questions.\n")
        L.append("| DB seed | system_a | system_b | B − A | McNemar p |")
        L.append("|---|---|---|---|---|")
        for seed in sens["seeds"]:
            s = sens["per_seed"][str(seed)]
            L.append(f"| {seed} | {s['system_a_accuracy']:.1%} "
                     f"({s['system_a_correct']}/{s['n']}) | "
                     f"{s['system_b_accuracy']:.1%} ({s['system_b_correct']}/{s['n']}) | "
                     f"{s['accuracy_difference_b_minus_a']:+.1%} | "
                     f"{s['mcnemar_p_value']:.4g} |")
        sp = sens["spread"]
        L.append("")
        L.append(f"Largest swing across seeds: system_a {sp['system_a_accuracy']:.1%}, "
                 f"system_b {sp['system_b_accuracy']:.1%}, "
                 f"B − A difference {sp['accuracy_difference_b_minus_a']:.1%}.")
        verdict = ("stable — every headline metric moves at most "
                   f"{sens['stability_threshold']:.0%} across seeds, so the headline "
                   f"numbers are a property of the systems, not of one database draw"
                   if sens["stable"] else
                   "seed-sensitive — at least one headline metric moves more than "
                   f"{sens['stability_threshold']:.0%} across seeds, so a headline "
                   f"difference that small could be database luck, not a system "
                   f"improvement")
        L.append(f"Verdict: the headline metrics are **{verdict}**.")
        L.append("")
    L.append("## Latency (per-question generation time, first pass)\n")
    L.append("| System | Mean | p95 |")
    L.append("|---|---|---|")
    for name, s in (("system_a", a), ("system_b", b)):
        lat = s["latency"]
        L.append(f"| {name} | {lat['mean_ms']:.2f} ms | {lat['p95_ms']:.2f} ms |")
    L.append("")
    L.append("The rule-based systems here answer in well under a millisecond, so "
             "these numbers are a floor, not a finding: they exist so that when an "
             "LLM-backed system is dropped into the same harness boundary, its "
             "latency cost shows up next to its accuracy gain instead of hiding "
             "behind it. A system that is 5 points more accurate but 100x slower "
             "is a different trade-off, and this table is where it becomes visible.")
    L.append("")
    flaky_a = a.get("flaky_questions")
    flaky_b = b.get("flaky_questions")
    if flaky_a is not None and flaky_b is not None:
        runs = flaky_a["runs"]
        L.append("## Flaky questions (pass-consistency across repeated runs)\n")
        L.append(f"Each system answered every question {runs} times in the "
                 f"repeated runs (plus the recorded first pass). A question "
                 f"that is right on some runs and wrong on others is flaky: "
                 f"its contribution to the headline accuracy is luck, not "
                 f"capability. For a deterministic system this list is empty "
                 f"— which is itself the finding. A non-deterministic system "
                 f"(for example an LLM-backed one) will show its wobble here "
                 f"first, before it shows up as noise in the headline number.\n")
        for name, flaky in (("system_a", flaky_a), ("system_b", flaky_b)):
            if flaky["flaky_count"] == 0:
                L.append(f"- {name}: **0 flaky questions** — every question "
                         f"was correct on every run or wrong on every run.")
            else:
                L.append(f"- {name}: **{flaky['flaky_count']} flaky "
                         f"question(s)** (least consistent first):\n")
                L.append("| ID | Category | Difficulty | Correct runs |")
                L.append("|---|---|---|---|")
                for q in flaky["questions"]:
                    L.append(f"| {q['id']} | {q['category']} | "
                             f"{q['difficulty']} | {q['correct_runs']}/"
                             f"{q['runs']} |")
                L.append("")
        L.append("")
    L.append("## Per-category accuracy\n")
    L.append("A category's headline percentage alone overstates how much "
             "is known when the category holds only a handful of "
             "questions: 100% on n=4 has a Wilson interval roughly "
             "[0.40, 1.00]. Read the interval, not just the point "
             "estimate — a wide interval means the category needs more "
             "questions before its accuracy can be trusted.\n")
    L.append("The B − A column is the paired difference inside the "
             "category, with its own bootstrap 95% CI: both systems "
             "answer the same questions, so this interval is narrower "
             "than the two Wilson intervals would suggest, and an "
             "interval that excludes 0 is evidence B really is better "
             "(or worse) than A *on that kind of question* — the "
             "headline difference alone cannot say where the "
             "improvement lives.\n")
    L.append("| Category | n | system_a | system_a 95% Wilson CI | system_b | system_b 95% Wilson CI | B − A | B − A 95% bootstrap CI |")
    L.append("|---|---|---|---|---|---|---|---|")
    for cat, v in res["per_category"].items():
        diff = v.get("difference_b_minus_a")
        diff_text = f"{diff:+.0%}" if diff is not None else "—"
        L.append(f"| {cat} | {v['n']} | {v['system_a_accuracy']:.0%} | "
                 f"{_wilson_cell(v.get('system_a_wilson_95ci'))} | "
                 f"{v['system_b_accuracy']:.0%} | "
                 f"{_wilson_cell(v.get('system_b_wilson_95ci'))} | "
                 f"{diff_text} | "
                 f"{_wilson_cell(v.get('difference_bootstrap_95ci'))} |")
    L.append("")
    L.append("## Per-difficulty accuracy\n")
    L.append("Same reading as the per-category table: a difficulty's "
             "headline percentage alone overstates how much is known "
             "when the difficulty holds only a handful of questions. "
             "Read the interval, not just the point estimate — a wide "
             "interval means the difficulty needs more questions before "
             "its accuracy can be trusted.\n")
    L.append("| Difficulty | n | system_a | system_a 95% Wilson CI | system_b | system_b 95% Wilson CI |")
    L.append("|---|---|---|---|---|---|")
    for diff, v in res["per_difficulty"].items():
        L.append(f"| {diff} | {v['n']} | {v['system_a_accuracy']:.0%} | "
                 f"{_wilson_cell(v.get('system_a_wilson_95ci'))} | "
                 f"{v['system_b_accuracy']:.0%} | "
                 f"{_wilson_cell(v.get('system_b_wilson_95ci'))} |")
    L.append("")
    mono = res.get("difficulty_monotonicity")
    if mono:
        L.append("## Difficulty monotonicity\n")
        L.append("Accuracy should fall easy → medium → hard: harder "
                 "questions should be harder. A system that scores "
                 "higher on a harder difficulty than on an easier one "
                 "is a warning — either the difficulty labels are "
                 "wrong for those questions, or the system has a "
                 "blind spot on the \"easier\" kind. Check the n in "
                 "the table above before reading much into a gap: a "
                 "violation on a 4-question cell is a handful of "
                 "questions, not a pattern.\n")
        for name in ("system_a", "system_b"):
            s = mono["systems"][name]
            if s["monotonic"]:
                L.append(f"- {name}: **monotonic** — accuracy falls "
                         f"{' → '.join(mono['difficulties'])} as it should.")
            else:
                parts = []
                for v in s["violations"]:
                    parts.append(
                        f"{v['harder']} {v['harder_accuracy']:.0%} "
                        f"(n={v['harder_n']}) beats {v['easier']} "
                        f"{v['easier_accuracy']:.0%} (n={v['easier_n']}) "
                        f"by {v['gap']:.0%}")
                L.append(f"- {name}: **not monotonic** — "
                         + "; ".join(parts) + ".")
        L.append("")
    matrix = res.get("coverage_matrix")
    if matrix:
        L.append("## Gold-set coverage matrix\n")
        L.append(f"Every category × difficulty cell should hold enough "
                 f"questions for its per-category and per-difficulty "
                 f"numbers to mean something. A cell with fewer than "
                 f"{matrix['thin_threshold']} questions is **thin**; an "
                 f"empty cell means that difficulty is unmeasured for "
                 f"that category at all. Growing the gold set should "
                 f"start with the empty cells, then the thin ones.\n")
        diffs = matrix["difficulties"]
        L.append("| Category | " + " | ".join(diffs) + " |")
        L.append("|---|" + "---|" * len(diffs))
        for cat in matrix["categories"]:
            row = matrix["cells"][cat]
            cells = [f"{row[d]} ⚠ empty" if row[d] == 0
                     else f"{row[d]} ⚠ thin" if row[d] < matrix["thin_threshold"]
                     else str(row[d])
                     for d in diffs]
            L.append(f"| {cat} | " + " | ".join(cells) + " |")
        L.append("")
        n_empty = len(matrix["empty_cells"])
        n_thin = len(matrix["thin_cells"])
        L.append(f"Coverage: {matrix['total_cells'] - n_empty - n_thin} of "
                 f"{matrix['total_cells']} cells have at least "
                 f"{matrix['thin_threshold']} questions, "
                 f"{n_thin} thin, {n_empty} empty.")
        if n_empty:
            L.append("Empty cells: " + ", ".join(
                f"{c['category']} / {c['difficulty']}"
                for c in matrix["empty_cells"]) + ".")
        if n_thin:
            L.append("Thin cells: " + ", ".join(
                f"{c['category']} / {c['difficulty']} ({c['count']})"
                for c in matrix["thin_cells"]) + ".")
        L.append("")
    dups = res.get("gold_duplicates")
    if dups:
        L.append("## Gold-set near-duplicates\n")
        if dups["total_groups"] == 0:
            L.append("No two gold questions share a normalised question or "
                     "the same gold SQL — every question measures something "
                     "distinct, at least by this check.")
        else:
            L.append(f"{dups['total_groups']} group(s) of gold questions "
                     f"measure the same thing twice: they share a "
                     f"normalised question (same wording, different case / "
                     f"punctuation) or the same gold SQL under different "
                     f"wording. A shared gold SQL is a paraphrase — it "
                     f"tests robustness to phrasing, but it also "
                     f"double-counts one query in the headline accuracy. "
                     f"A shared question is a plain repeat.\n")
            L.append("| Kind | IDs | Shared text / SQL |")
            L.append("|---|---|---|")
            for g in dups["groups"]:
                shared = g["shared"].replace("|", "\\|")
                L.append(f"| {g['kind']} | {', '.join(g['ids'])} | `{shared}` |")
        L.append("")
    split = res.get("split_half")
    if split:
        h1, h2 = split["halves"]["half_1"], split["halves"]["half_2"]
        g = split["gap"]
        L.append("## Split-half reliability\n")
        L.append("The gold set is split into two interleaved halves "
                 "(even- vs odd-positioned questions, so both halves "
                 "span every category). If a headline accuracy is real, "
                 "both halves should tell roughly the same story; if it "
                 "is driven by one half of the questions, the halves "
                 "diverge — and so does the B − A improvement.\n")
        L.append("| Half | n | system_a | system_b | B − A |")
        L.append("|---|---|---|---|---|")
        for label, h in (("Half 1", h1), ("Half 2", h2)):
            L.append(f"| {label} | {h['n']} | "
                     f"{h['system_a_accuracy']:.1%} "
                     f"({h['system_a_correct']}/{h['n']}) | "
                     f"{h['system_b_accuracy']:.1%} "
                     f"({h['system_b_correct']}/{h['n']}) | "
                     f"{h['accuracy_difference_b_minus_a']:+.1%} |")
        L.append("")
        L.append(f"Half-to-half gap: system_a {g['system_a']:.1%}, "
                 f"system_b {g['system_b']:.1%}, "
                 f"B − A difference "
                 f"{g['accuracy_difference_b_minus_a']:.1%}.")
        verdict = ("balanced — every gap is within "
                   f"{split['balance_threshold']:.0%}, so the headline "
                   f"numbers are not carried by one half of the gold set"
                   if split["balanced"] else
                   "unbalanced — at least one gap exceeds "
                   f"{split['balance_threshold']:.0%}, so a headline "
                   f"number that large could be an artefact of which "
                   f"half of the questions happened to be asked")
        L.append(f"Verdict: the split-half reliability is **{verdict}**.")
        L.append("")
    L.append("## Error analysis — system_a\n")
    if res["system_a_errors"]:
        counts = Counter(r["error"] for r in res["system_a_errors"])
        L.append(f"system_a failed {len(res['system_a_errors'])} of {a['n']} questions. "
                 f"Error categories: {dict(counts)}.\n")
        L.append("| ID | Category | Error | Candidate SQL |")
        L.append("|---|---|---|---|")
        for r in res["system_a_errors"]:
            L.append(f"| {r['id']} | {r['category']} | {r['error']} | `{r['candidate_sql']}` |")
        L.append("")
        L.append("Reading: system_a's failures are not random. They cluster exactly on "
                 "questions with a side, status, country, or date-range filter, and on "
                 "average-price questions — the documented weaknesses in `systems.py`. That clustering, "
                 "not the headline number, is what tells engineering what to fix, and "
                 "system_b is precisely that fix.")
    else:
        L.append("No errors.")
    cross = res.get("error_cross_tab")
    if cross:
        L.append("")
        L.append("## Error-type × category cross-tab\n")
        L.append("Which error types cluster in which categories: one row per "
                 "category, one column per error type, a cell counts that "
                 "system's failures of that type in that category. The bold "
                 "count in a row is that category's dominant error — the "
                 "failure mode to fix first for that kind of question. A "
                 "column that is all zeros is itself a finding: that error "
                 "never happens anywhere.\n")
        for name in ("system_a", "system_b"):
            tab = cross["systems"][name]
            if tab["total_errors"] == 0:
                L.append(f"- {name}: **0 failures** — nothing to cross-tabulate.")
                continue
            L.append(f"### {name} ({tab['total_errors']} failures)\n")
            L.append("| Category | " + " | ".join(cross["error_types"])
                     + " | Total |")
            L.append("|---|" + "---|" * (len(cross["error_types"]) + 1))
            for cat in cross["categories"]:
                cells = []
                for err in cross["error_types"]:
                    n = tab["cells"][cat][err]
                    cell = (f"**{n}**"
                            if n and tab["dominant_error"][cat] == err
                            else str(n))
                    cells.append(cell)
                L.append(f"| {cat} | " + " | ".join(cells)
                         + f" | {tab['category_totals'][cat]} |")
            L.append("")
            dom = defaultdict(list)
            for cat in cross["categories"]:
                if tab["dominant_error"][cat]:
                    dom[tab["dominant_error"][cat]].append(cat)
            parts = []
            for err in cross["error_types"]:
                if err in dom:
                    cats = dom[err]
                    parts.append(f"{err} dominates {len(cats)} "
                                 f"{'category' if len(cats) == 1 else 'categories'} "
                                 f"({', '.join(cats)})")
            L.append("Dominant error per category: " + "; ".join(parts) + ".")
            L.append("")
    if failures_csv:
        L.append("")
        L.append(f"Full failure list for manual error review: `{failures_csv}` "
                 f"(one row per failed question, both systems).")
    L.append("")
    if j:
        L.append("## Judge calibration (judge vs human labels)\n")
        ci = j.get("cohens_kappa_bootstrap_95ci")
        ci_text = (f" (95% bootstrap CI [{ci[0]:.3f}, {ci[1]:.3f}])"
                   if ci else "")
        L.append(f"On {j['n']} human-labelled answers, the heuristic judge agreed with "
                 f"humans {j['agreement']:.1%} of the time: **Cohen's kappa = "
                 f"{j['cohens_kappa']:.3f}**{ci_text} (moderate agreement), precision "
                 f"{j['precision_correct']:.3f}, recall {j['recall_correct']:.3f}, "
                 f"confusion {j['confusion']}.")
        L.append("")
        L.append("Conclusion: at kappa ≈ 0.55 this judge is useful as a cheap first pass "
                 "but **must not gate a release alone** — it is fooled by the right number "
                 "attached to the wrong symbol/side/metric, and it rejects correct answers "
                 "written in words or sensibly rounded. Execution accuracy against ground "
                 "truth remains the headline metric; the judge is a supplement with known, "
                 "measured limits.")
        patterns = j.get("disagreement_patterns")
        if patterns and patterns["total"]:
            counts = patterns["counts"]
            L.append("")
            L.append("### Disagreement patterns\n")
            L.append(f"The judge disagreed with humans on {patterns['total']} "
                     f"labelled answers. Classified by pattern — the false "
                     f"positives are the judge matching the right number to "
                     f"the wrong thing, the false negatives are right "
                     f"answers its verbatim number matching cannot see:\n")
            L.append("| Pattern | Shape | Count |")
            L.append("|---|---|---|")
            for pat, n in sorted(counts.items(),
                                 key=lambda kv: (-kv[1], kv[0])):
                L.append(f"| {pat} | {DISAGREEMENT_PATTERNS[pat]} | {n} |")
            L.append("")
            L.append("Per disagreement: " + ", ".join(
                f"{d['id']} ({d['pattern']})"
                for d in j["disagreements"]) + ".")
            L.append("")
            L.append("Reading: the pattern counts say where the judge's "
                     "matching is blind. Wrong-symbol / wrong-side / "
                     "wrong-metric false positives all come from matching "
                     "a bare number with no check on what the number "
                     "refers to — fixing the judge means checking the "
                     "referent, not the number. Wording and rounding "
                     "false negatives are the same lesson from the other "
                     "side: a correct answer need not repeat the gold "
                     "digits verbatim.")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=None,
                    help="evaluate under a single DB seed (overrides the default two-seed run)")
    ap.add_argument("--seeds", type=int, nargs="+", default=None,
                    help="evaluate under each DB seed and report headline-metric stability "
                         "(default: 42 1234)")
    ap.add_argument("--category", nargs="+", default=None, metavar="CATEGORY",
                    help="run the eval on a subset of gold categories only, "
                         "for targeted iteration (e.g. --category "
                         "count_by_date_range avg_price_by_symbol); "
                         "unknown categories fail with the available list")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "results"))
    ap.add_argument("--failures-csv", default=None,
                    help="where to write the failures CSV (default: "
                         "<out-dir>/failures.csv)")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"),
                    help="diff two results.json files instead of running the eval")
    ap.add_argument("--compare-out", default=None,
                    help="also write the comparison report to this file")
    args = ap.parse_args()

    if args.compare:
        with open(args.compare[0]) as f:
            old = json.load(f)
        with open(args.compare[1]) as f:
            new = json.load(f)
        report = render_compare(compare_results(old, new))
        print(report, end="")
        if args.compare_out:
            with open(args.compare_out, "w") as f:
                f.write(report)
            print(f"wrote {args.compare_out}")
        return

    if args.seeds:
        seeds = args.seeds
    elif args.seed is not None:
        seeds = [args.seed]
    else:
        seeds = list(DEFAULT_SEEDS)
    res = run(runs=args.runs, seeds=seeds, categories=args.category)
    os.makedirs(args.out_dir, exist_ok=True)
    failures_path = args.failures_csv or os.path.join(args.out_dir, "failures.csv")
    failures_rel = os.path.relpath(failures_path, ROOT)
    with open(os.path.join(args.out_dir, "results.json"), "w") as f:
        json.dump(res, f, indent=2)
    with open(os.path.join(args.out_dir, "report.md"), "w") as f:
        f.write(render_report(res, failures_csv=failures_rel))
    gold = load_jsonl(os.path.join(ROOT, "data", "gold.jsonl"))
    n_failures = write_failures_csv(res, failures_path, gold=gold)
    print(f"wrote {failures_rel} ({n_failures} failures)")
    for name in ("system_a", "system_b"):
        s = res["systems"][name]
        lat = s["latency"]
        print(f"{name}: execution accuracy {s['execution_accuracy']:.1%} "
              f"({s['correct']}/{s['n']}), exact match {s['exact_match_rate']:.1%}, "
              f"pass-consistency {s['pass_consistency_mean']:.3f}, "
              f"latency mean {lat['mean_ms']:.2f} ms / p95 {lat['p95_ms']:.2f} ms")
    mc = res["comparison"]["mcnemar"]
    print(f"McNemar: b={mc['b']} c={mc['c']} p={mc['p_value']:.4g}")
    strat = res.get("stratified_accuracy")
    if strat:
        print(f"stratified accuracy (equal-weight by difficulty): "
              f"system_a {strat['system_a_stratified_accuracy']:.1%}, "
              f"system_b {strat['system_b_stratified_accuracy']:.1%} "
              f"(B-A {strat['stratified_difference_b_minus_a']:+.1%})")
    sens = res.get("seed_sensitivity")
    if sens:
        for seed in sens["seeds"]:
            s = sens["per_seed"][str(seed)]
            print(f"seed {seed}: system_a {s['system_a_accuracy']:.1%} "
                  f"system_b {s['system_b_accuracy']:.1%} "
                  f"(B-A {s['accuracy_difference_b_minus_a']:+.1%})")
        sp = sens["spread"]
        print(f"seed sensitivity: max swing system_a {sp['system_a_accuracy']:.1%}, "
              f"system_b {sp['system_b_accuracy']:.1%}, "
              f"B-A {sp['accuracy_difference_b_minus_a']:.1%} — "
              f"{'stable' if sens['stable'] else 'SEED-SENSITIVE'}")
    print(f"wrote {args.out_dir}/results.json, report.md and failures.csv")


if __name__ == "__main__":
    main()
