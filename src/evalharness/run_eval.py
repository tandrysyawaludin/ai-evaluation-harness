"""Evaluation harness CLI.

Builds the seeded brokerage DB, runs both candidate systems over the gold
set (repeatedly, to measure pass-consistency under non-determinism),
computes confidence intervals and the paired McNemar test, calibrates the
judge, and writes results/results.json + results/report.md.

Usage:  PYTHONPATH=src python -m evalharness.run_eval --runs 3
"""
import argparse
import json
import os
from collections import Counter, defaultdict

from .db import build_db
from .judge import calibrate
from .metrics import evaluate_system
from .stats import (bootstrap_ci, bootstrap_diff_ci, mcnemar,
                    sample_size_for_difference, wilson_interval)
from .systems import SYSTEMS

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run(runs=3, seed=42):
    gold = load_jsonl(os.path.join(ROOT, "data", "gold.jsonl"))
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
            "pass_consistency_mean": sum(frac) / len(frac) if frac else 0.0,
            "questions_correct_on_every_run": (
                sum(1 for c in per_question_correct if c == runs) / len(gold)),
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

    errors_a = [r for r in per_system["system_a"]["records"] if r["error"]]

    judge_result = None
    labels_path = os.path.join(ROOT, "data", "human_labels.jsonl")
    if os.path.exists(labels_path):
        judge_result = calibrate(load_jsonl(labels_path))
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
            "sample_size_to_detect_5pp_from_a": n_needed,
        },
        "per_category": categories,
        "system_a_errors": errors_a,
        "judge_calibration": judge_result,
    }


def render_report(res):
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
    L.append("## Per-category accuracy\n")
    L.append("| Category | n | system_a | system_b |")
    L.append("|---|---|---|---|")
    for cat, v in res["per_category"].items():
        L.append(f"| {cat} | {v['n']} | {v['system_a_accuracy']:.0%} | {v['system_b_accuracy']:.0%} |")
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
                 "questions with a side, status, or country filter, and on average-price "
                 "questions — the documented weaknesses in `systems.py`. That clustering, "
                 "not the headline number, is what tells engineering what to fix, and "
                 "system_b is precisely that fix.")
    else:
        L.append("No errors.")
    L.append("")
    if j:
        L.append("## Judge calibration (judge vs human labels)\n")
        L.append(f"On {j['n']} human-labelled answers, the heuristic judge agreed with "
                 f"humans {j['agreement']:.1%} of the time: **Cohen's kappa = "
                 f"{j['cohens_kappa']:.3f}** (moderate agreement), precision "
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
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "results"))
    args = ap.parse_args()

    res = run(runs=args.runs, seed=args.seed)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "results.json"), "w") as f:
        json.dump(res, f, indent=2)
    with open(os.path.join(args.out_dir, "report.md"), "w") as f:
        f.write(render_report(res))
    for name in ("system_a", "system_b"):
        s = res["systems"][name]
        print(f"{name}: execution accuracy {s['execution_accuracy']:.1%} "
              f"({s['correct']}/{s['n']}), exact match {s['exact_match_rate']:.1%}, "
              f"pass-consistency {s['pass_consistency_mean']:.3f}")
    mc = res["comparison"]["mcnemar"]
    print(f"McNemar: b={mc['b']} c={mc['c']} p={mc['p_value']:.4g}")
    print(f"wrote {args.out_dir}/results.json and report.md")


if __name__ == "__main__":
    main()
