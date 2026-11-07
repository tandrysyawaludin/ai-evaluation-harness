"""Diff two results.json files produced by run_eval.

Answers the question "did the system get better or worse since the last
run?" without re-running the eval: per-system accuracy deltas with a
paired McNemar test on the same questions, the exact questions that
flipped correctness in either direction, per-category deltas, error-count
changes, and the judge-kappa delta when both runs were calibrated.

Both files must cover the same gold set (same question ids); comparing
runs over different gold sets would silently compare different questions,
so that is an error, not a warning. Different DB seeds are allowed — the
seed-sensitivity question is real — but the report flags it.
"""
from collections import Counter, defaultdict

from .stats import mcnemar

SYSTEMS = ("system_a", "system_b")


def _records_by_id(res, system):
    try:
        records = res["systems"][system]["records"]
    except KeyError as e:
        raise ValueError(f"results file is missing systems.{system}.records") from e
    return {r["id"]: r for r in records}


def _per_category(records):
    by_cat = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in records.values():
        c = by_cat[r["category"]]
        c["n"] += 1
        c["correct"] += int(r["execution_correct"])
    return {cat: {"n": v["n"], "accuracy": v["correct"] / v["n"]}
            for cat, v in sorted(by_cat.items())}


def _system_diff(old, new, system):
    old_recs = _records_by_id(old, system)
    new_recs = _records_by_id(new, system)
    old_ids, new_ids = set(old_recs), set(new_recs)
    if old_ids != new_ids:
        missing = sorted(old_ids - new_ids)
        added = sorted(new_ids - old_ids)
        raise ValueError(
            f"cannot compare {system}: question ids differ "
            f"(only in old: {missing}, only in new: {added})")

    old_flags = [old_recs[i]["execution_correct"] for i in sorted(old_ids)]
    new_flags = [new_recs[i]["execution_correct"] for i in sorted(old_ids)]
    flips = [
        {"id": qid, "category": old_recs[qid]["category"],
         "difficulty": old_recs[qid]["difficulty"],
         "old_correct": old_recs[qid]["execution_correct"],
         "new_correct": new_recs[qid]["execution_correct"]}
        for qid in sorted(old_ids)
        if old_recs[qid]["execution_correct"] != new_recs[qid]["execution_correct"]
    ]
    old_cat = _per_category(old_recs)
    new_cat = _per_category(new_recs)
    category_delta = {
        cat: {"n": new_cat[cat]["n"],
              "old_accuracy": old_cat[cat]["accuracy"],
              "new_accuracy": new_cat[cat]["accuracy"],
              "delta": new_cat[cat]["accuracy"] - old_cat[cat]["accuracy"]}
        for cat in old_cat
    }
    old_err = Counter(old["systems"][system].get("error_counts", {}))
    new_err = Counter(new["systems"][system].get("error_counts", {}))
    error_delta = {e: new_err[e] - old_err[e]
                   for e in sorted(set(old_err) | set(new_err))
                   if new_err[e] != old_err[e]}
    old_sys, new_sys = old["systems"][system], new["systems"][system]
    old_lat, new_lat = old_sys["latency"], new_sys["latency"]
    return {
        "old_accuracy": old_sys["execution_accuracy"],
        "new_accuracy": new_sys["execution_accuracy"],
        "delta": new_sys["execution_accuracy"] - old_sys["execution_accuracy"],
        "old_correct": old_sys["correct"],
        "new_correct": new_sys["correct"],
        "n": old_sys["n"],
        "mcnemar": mcnemar(old_flags, new_flags),
        "fixed": [f for f in flips if f["new_correct"]],
        "regressed": [f for f in flips if not f["new_correct"]],
        "per_category": category_delta,
        "error_delta": error_delta,
        "latency_delta_ms": {
            "mean_ms": new_lat["mean_ms"] - old_lat["mean_ms"],
            "p95_ms": new_lat["p95_ms"] - old_lat["p95_ms"],
        },
    }


def compare_results(old, new):
    """Diff two run_eval result dicts. Raises ValueError on mismatched gold sets."""
    old_ids = {r["id"] for r in _records_by_id(old, "system_a").values()}
    new_ids = {r["id"] for r in _records_by_id(new, "system_a").values()}
    if old_ids != new_ids:
        raise ValueError(
            "cannot compare: gold sets differ "
            f"(only in old: {sorted(old_ids - new_ids)}, "
            f"only in new: {sorted(new_ids - old_ids)})")
    old_j = (old.get("judge_calibration") or {}).get("cohens_kappa")
    new_j = (new.get("judge_calibration") or {}).get("cohens_kappa")
    return {
        "gold_size": len(old_ids),
        "old_db_seed": old.get("db_seed"),
        "new_db_seed": new.get("db_seed"),
        "same_db_seed": old.get("db_seed") == new.get("db_seed"),
        "systems": {s: _system_diff(old, new, s) for s in SYSTEMS},
        "judge_kappa": {
            "old": old_j, "new": new_j,
            "delta": (new_j - old_j) if old_j is not None and new_j is not None else None,
        },
    }


def render_compare(diff):
    L = ["# Run comparison\n"]
    L.append(f"Gold set: **{diff['gold_size']} questions** · "
             f"DB seed {diff['old_db_seed']} → {diff['new_db_seed']}")
    if not diff["same_db_seed"]:
        L.append("⚠ DB seeds differ: part of any change may be seed noise, "
                 "not a system change — re-run with the same seed to confirm.")
    L.append("")
    for name in SYSTEMS:
        s = diff["systems"][name]
        L.append(f"## {name}\n")
        L.append(f"Accuracy: {s['old_accuracy']:.1%} ({s['old_correct']}/{s['n']}) → "
                 f"{s['new_accuracy']:.1%} ({s['new_correct']}/{s['n']}), "
                 f"**{s['delta']:+.1%}**")
        mc = s["mcnemar"]
        verdict = ("significant at the 5% level"
                   if mc["p_value"] < 0.05 else "not significant at the 5% level")
        L.append(f"Paired McNemar on the same questions: fixed {len(s['fixed'])}, "
                 f"regressed {len(s['regressed'])}, p = {mc['p_value']:.4g} "
                 f"({verdict}).")
        lat = s["latency_delta_ms"]
        L.append(f"Latency delta (mean / p95): {lat['mean_ms']:+.2f} ms / "
                 f"{lat['p95_ms']:+.2f} ms")
        for label, flips in (("Fixed (wrong → right)", s["fixed"]),
                             ("Regressed (right → wrong)", s["regressed"])):
            if flips:
                L.append(f"\n{label}:")
                for f in flips:
                    L.append(f"- {f['id']} ({f['category']}, {f['difficulty']})")
        moved = {c: v for c, v in s["per_category"].items() if v["delta"] != 0}
        if moved:
            L.append("\nPer-category accuracy change:")
            for cat, v in moved.items():
                L.append(f"- {cat}: {v['old_accuracy']:.0%} → "
                         f"{v['new_accuracy']:.0%} ({v['delta']:+.0%}, n={v['n']})")
        if s["error_delta"]:
            L.append("\nError-count change: " + ", ".join(
                f"{e} {d:+d}" for e, d in s["error_delta"].items()))
        L.append("")
    j = diff["judge_kappa"]
    if j["delta"] is not None:
        L.append(f"Judge Cohen's kappa: {j['old']:.3f} → {j['new']:.3f} "
                 f"({j['delta']:+.3f})")
    elif j["old"] is not None or j["new"] is not None:
        L.append("Judge kappa: only one run was calibrated, so no delta.")
    return "\n".join(L).rstrip() + "\n"
