"""Sample-size planner CLI.

Answers the question the harness otherwise leaves implicit: "how many
gold questions do we need before an improvement of X percentage points
is detectable, rather than noise?" Built on the normal approximation in
stats.sample_size_for_difference — per-group n for a two-proportion
comparison, so a paired gold set needs at least that many questions.

Usage:
  PYTHONPATH=src python -m evalharness.plan --baseline 0.53 --delta 0.05
  PYTHONPATH=src python -m evalharness.plan --from-results results/results.json
  PYTHONPATH=src python -m evalharness.plan --baseline 0.53 --table
  PYTHONPATH=src python -m evalharness.plan --baseline 0.53 --json
"""
import argparse
import json
import os
import sys

from .stats import sample_size_for_difference

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DELTAS = (0.02, 0.05, 0.10, 0.15, 0.20)
DEFAULT_POWERS = (0.8, 0.9)


def plan(baseline, delta, alpha=0.05, power=0.8, current_n=None):
    """One plan: n needed to detect baseline -> baseline+delta.

    current_n, when given, is the size of the gold set already held, so
    the verdict says whether that set can already detect the effect.
    """
    n = sample_size_for_difference(baseline, delta, alpha=alpha, power=power)
    result = {
        "baseline": baseline,
        "delta": delta,
        "target": baseline + delta,
        "alpha": alpha,
        "power": power,
        "n_per_group": n,
    }
    if current_n is not None:
        result["current_n"] = current_n
        result["sufficient"] = current_n >= n
        result["shortfall"] = max(0, n - current_n)
    return result


def plan_table(baseline, deltas=DEFAULT_DELTAS, powers=DEFAULT_POWERS,
               alpha=0.05):
    """Grid of plans: rows are deltas, columns are powers."""
    return [{**plan(baseline, d, alpha=alpha, power=p), "power": p}
            for d in deltas for p in powers]


def baseline_from_results(results_path, system="system_a"):
    """Read a system's accuracy and the gold-set size from results.json."""
    with open(results_path) as f:
        results = json.load(f)
    accuracy = results["systems"][system]["execution_accuracy"]
    return accuracy, results["gold_size"]


def render_single(p):
    lines = [
        f"Baseline accuracy: {p['baseline']:.1%} -> target {p['target']:.1%} "
        f"(+{p['delta']:.0%}), alpha {p['alpha']:.2g}, power {p['power']:.0%}",
        f"Gold questions needed (per group): {p['n_per_group']}",
    ]
    if "current_n" in p:
        if p["sufficient"]:
            lines.append(f"Current gold set ({p['current_n']}) is sufficient: "
                         f"it already covers this effect size.")
        else:
            lines.append(f"Current gold set ({p['current_n']}) is NOT sufficient: "
                         f"add {p['shortfall']} more questions to detect "
                         f"this effect size.")
    return "\n".join(lines)


def render_table(baseline, rows, powers):
    header = f"Baseline accuracy: {baseline:.1%}  (n per group)\n"
    header += f"{'Delta':>7}" + "".join(f"{f'power {p:.0%}':>14}" for p in powers)
    lines = [header]
    by_delta = {}
    for r in rows:
        by_delta.setdefault(r["delta"], {})[r["power"]] = r["n_per_group"]
    for delta in sorted(by_delta):
        row = f"{delta:+.0%}".rjust(7)
        row += "".join(f"{by_delta[delta][p]:>14,}" for p in powers)
        lines.append(row)
    lines.append("\nRead: detecting a small effect needs a large gold set; "
                 "a 20pp jump is visible with a few dozen questions.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Plan gold-set size for detecting an accuracy improvement.")
    ap.add_argument("--baseline", type=float, default=None,
                    help="baseline accuracy, e.g. 0.53")
    ap.add_argument("--from-results", default=None,
                    help="results.json to take the baseline accuracy and "
                         "current gold-set size from")
    ap.add_argument("--system", default="system_a",
                    help="system whose accuracy is the baseline (default: system_a)")
    ap.add_argument("--delta", type=float, default=0.05,
                    help="minimum detectable improvement, as a proportion "
                         "(default: 0.05)")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, default=0.8)
    ap.add_argument("--current-n", type=int, default=None,
                    help="size of the gold set already held")
    ap.add_argument("--table", action="store_true",
                    help="print a delta x power grid instead of one plan")
    ap.add_argument("--json", action="store_true",
                    help="emit the plan as JSON instead of text")
    args = ap.parse_args(argv)

    if args.from_results:
        try:
            baseline, gold_size = baseline_from_results(args.from_results,
                                                        args.system)
        except (OSError, KeyError, ValueError) as exc:
            ap.error(f"cannot read baseline from {args.from_results}: {exc}")
        current_n = args.current_n if args.current_n is not None else gold_size
    else:
        if args.baseline is None:
            ap.error("--baseline is required unless --from-results is given")
        baseline = args.baseline
        current_n = args.current_n

    try:
        if args.table:
            rows = plan_table(baseline, alpha=args.alpha)
            output = (json.dumps({"baseline": baseline, "alpha": args.alpha,
                                  "plans": rows}, indent=2)
                      if args.json
                      else render_table(baseline, rows, DEFAULT_POWERS))
        else:
            result = plan(baseline, args.delta, alpha=args.alpha,
                          power=args.power, current_n=current_n)
            output = (json.dumps(result, indent=2) if args.json
                      else render_single(result))
    except ValueError as exc:
        ap.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
