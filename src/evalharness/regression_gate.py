"""CI regression gate.

Fails (exit 1) if the reference system's execution accuracy in a results
file has dropped more than TOLERANCE (2 percentage points) below the
recorded baseline in results/baseline.json.

Usage:  PYTHONPATH=src python -m evalharness.regression_gate [results.json]
"""
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOLERANCE = 0.02
SYSTEM = "system_b"


def check(current_accuracy, baseline_accuracy, tolerance=TOLERANCE):
    return current_accuracy >= baseline_accuracy - tolerance


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    results_path = argv[0] if argv else os.path.join(ROOT, "results", "results.json")
    with open(os.path.join(ROOT, "results", "baseline.json")) as f:
        baseline = json.load(f)
    with open(results_path) as f:
        results = json.load(f)
    base_acc = baseline[SYSTEM]["execution_accuracy"]
    cur_acc = results["systems"][SYSTEM]["execution_accuracy"]
    drop = base_acc - cur_acc
    print(f"{SYSTEM}: baseline {base_acc:.1%} | current {cur_acc:.1%} | "
          f"drop {drop:+.1%} | tolerance {TOLERANCE:.0%}")
    if check(cur_acc, base_acc):
        print("REGRESSION GATE: PASS")
        return 0
    print("REGRESSION GATE: FAIL — accuracy dropped more than 2pp below baseline")
    return 1


if __name__ == "__main__":
    sys.exit(main())
