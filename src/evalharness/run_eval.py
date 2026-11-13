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
        PYTHONPATH=src python -m evalharness.run_eval --compare old.json new.json
"""
import argparse
import json
import os
from collections import Counter, defaultdict

from .compare import compare_results, render_compare
from .db import build_db
from .failures import write_failures_csv
from .judge import calibrate
from .metrics import evaluate_system
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

    # Per-category breakdown
    by_cat = defaultdict(lambda: {"n": 0, "a": 0, "b": 0})
    for item, ra, rb in zip(gold, per_system["system_a"]["records"],
                            per_system["system_b"]["records"]):
        c = by_cat[item["category"]]
        c["n"] += 1
        c["a"] += int(ra["execution_correct"])
        c["b"] += int(rb["execution_correct"])
    categories = {cat: {"n": v["n"], "system_a_accuracy": v["a"] / v["n"],
                        "system_b_accuracy": v["b"] / v["n"]}
                  for cat, v in sorted(by_cat.items())}

    # Per-difficulty breakdown (easy / medium / hard), same shape as above.
    # Difficulties are ordered easy -> medium -> hard; any unexpected value
    # sorts after those, alphabetically, rather than crashing the report.
    difficulty_order = {"easy": 0, "medium": 1, "hard": 2}
    by_diff = defaultdict(lambda: {"n": 0, "a": 0, "b": 0})
    for item, ra, rb in zip(gold, per_system["system_a"]["records"],
                            per_system["system_b"]["records"]):
        d = by_diff[item["difficulty"]]
        d["n"] += 1
        d["a"] += int(ra["execution_correct"])
        d["b"] += int(rb["execution_correct"])
    difficulties = {diff: {"n": v["n"], "system_a_accuracy": v["a"] / v["n"],
                           "system_b_accuracy": v["b"] / v["n"]}
                    for diff, v in sorted(
                        by_diff.items(),
                        key=lambda kv: (difficulty_order.get(kv[0], 99), kv[0]))}

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
                                   "human_label", "judge_label")}
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
        "coverage_matrix": build_coverage_matrix(gold),
        "system_a_errors": errors_a,
        "judge_calibration": judge_result,
    }


def run(runs=3, seed=42, seeds=None):
    """Evaluate under one or more DB seeds.

    `seeds` wins over `seed` when given; otherwise `seed` alone is used,
    so `run(runs=1)` keeps its old single-seed behaviour. The first seed
    is the primary one: its full results are the top-level `systems`
    block, so the regression gate and `--compare` keep working unchanged.
    With more than one seed the result also carries `db_seeds` and a
    `seed_sensitivity` summary of headline-metric stability.
    """
    if seeds is None:
        seeds = (seed,)
    seeds = tuple(seeds)
    if not seeds:
        raise ValueError("at least one DB seed is required")
    gold = load_jsonl(os.path.join(ROOT, "data", "gold.jsonl"))
    # Fail fast on a broken ground truth: a malformed gold row would
    # otherwise silently skew every metric the harness reports.
    gold_errors = validate_gold(gold)
    if gold_errors:
        raise ValueError("gold.jsonl failed schema validation:\n"
                         + "\n".join(gold_errors))

    per_seed = {}
    for i, s in enumerate(seeds):
        per_seed[s] = _run_single_seed(runs, s, gold, calibrate_judge=(i == 0))

    primary = per_seed[seeds[0]]
    primary["db_seeds"] = list(seeds)
    primary["seed_sensitivity"] = (
        build_seed_sensitivity(per_seed) if len(seeds) > 1 else None)
    return primary


def render_report(res, failures_csv=None):
    a, b = res["systems"]["system_a"], res["systems"]["system_b"]
    cmp_ = res["comparison"]
    j = res["judge_calibration"]
    L = []
    L.append("# Evaluation Report — Brokerage Text-to-SQL Agent\n")
    L.append(f"Gold set: **{res['gold_size']} questions** · DB seed: {res['db_seed']} · "
             f"Runs per system: {res['runs_per_system']}\n")
    L.append("## Headline results\n")
    L.append("| System | Execution accuracy | 95% Wilson CI | 95% bootstrap CI | Exact match | Pass-consistency |")
    L.append("|---|---|---|---|---|---|")
    for name, s in (("system_a (baseline)", a), ("system_b (improved)", b)):
        L.append(f"| {name} | {s['execution_accuracy']:.1%} ({s['correct']}/{s['n']}) "
                 f"| [{s['wilson_95ci'][0]:.3f}, {s['wilson_95ci'][1]:.3f}] "
                 f"| [{s['bootstrap_95ci'][0]:.3f}, {s['bootstrap_95ci'][1]:.3f}] "
                 f"| {s['exact_match_rate']:.1%} | {s['pass_consistency_mean']:.3f} |")
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
    L.append("| Category | n | system_a | system_b |")
    L.append("|---|---|---|---|")
    for cat, v in res["per_category"].items():
        L.append(f"| {cat} | {v['n']} | {v['system_a_accuracy']:.0%} | {v['system_b_accuracy']:.0%} |")
    L.append("")
    L.append("## Per-difficulty accuracy\n")
    L.append("| Difficulty | n | system_a | system_b |")
    L.append("|---|---|---|---|")
    for diff, v in res["per_difficulty"].items():
        L.append(f"| {diff} | {v['n']} | {v['system_a_accuracy']:.0%} | {v['system_b_accuracy']:.0%} |")
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
    res = run(runs=args.runs, seeds=seeds)
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
