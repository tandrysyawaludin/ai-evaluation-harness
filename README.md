# AI Evaluation Harness for a Brokerage Text-to-SQL Agent

> A portfolio project for a **Senior Data Scientist, AI Evaluation** role.
> It does not just *call* an LLM. It answers the harder question that role owns:
> **how do we know whether the model's answers are actually right — and how do we prove it, statistically, before we ship?**

## The problem

A brokerage analytics agent that answers questions like *"What was the total
BUY volume for NVDA from clients in Japan?"* can sound fluent and still be
wrong. In brokerage, a wrong number is not a UX bug — it is a business and
risk problem. Fluency is not correctness.

This project builds the evaluation practice around such an agent:

- a **ground-truth** text-to-SQL dataset over a realistic brokerage database,
- two candidate systems (a flawed baseline and an improved system) so a real
  A/B measurement is possible,
- **execution accuracy** measured against the database, not against vibes,
- statistical treatment worthy of an experiment: Wilson and bootstrap
  confidence intervals, and McNemar's test for the paired A/B comparison,
- an **LLM-as-judge calibration** study: the automated judge is itself
  evaluated against human labels (Cohen's kappa, precision/recall) before
  anyone is allowed to trust it,
- repeated-run **stability** checks for non-determinism, and
- a **CI regression gate** that fails a build if quality drops more than
  2 percentage points from the recorded baseline.

Everything runs on the **Python standard library only** (`sqlite3`, `json`,
`re`, `random`, `statistics`, `math`, `unittest`). No API keys, no installs,
no network. If you have Python 3.10+, you can reproduce every number below.

## Results

Measured on the checked-in gold set (`data/gold.jsonl`), database seed 42.
Reproduce with the commands under *How to run* — do not take this table on faith.

| System | Execution accuracy | 95% Wilson CI | Exact-match (SQL) |
|---|---|---|---|
| system_a (baseline) | 52.7% (29/55) | [0.398, 0.653] | 52.7% |
| system_b (improved) | 100.0% (55/55) | [0.935, 1.000] | 100.0% |

The improvement is not noise: paired McNemar's test on the same 55
questions gives b = 26, c = 0, **p = 9.4e-07**, with a bootstrap 95% CI for
the +47.3pp difference of [+0.345, +0.618]. Judge calibration on 44
human-labelled answers: agreement 77.3%, **Cohen's kappa = 0.545**,
precision/recall 0.773 — measured, moderate, and explicitly *not* good
enough to gate a release alone (see the report).

Per-category breakdown, judge calibration, and error analysis are in
[`results/report.md`](results/report.md), with the machine-readable
version in `results/results.json`.

## What this proves — mapped to the job requirements

| Job requirement | Where it is demonstrated |
|---|---|
| Design AI evaluations: ground truth, metrics, scoring | `src/evalharness/gold.py`, `data/gold.jsonl`, `docs/DESIGN.md` |
| Build repeatable eval loops, catch regressions before release | `src/evalharness/run_eval.py`, `src/evalharness/regression_gate.py`, `.github/workflows/ci.yml` |
| Treat evaluations as experiments: sample sizing, CIs, significance | `src/evalharness/stats.py` (Wilson, bootstrap, McNemar, sample-size estimator) |
| Validate automated graders against human ground truth | `src/evalharness/judge.py`, `data/human_labels.jsonl` (Cohen's kappa, confusion matrix) |
| Proficiency in Python and SQL, evaluating models in production-style environments | The whole harness; systems generate SQL executed against SQLite |
| Evaluating text-to-SQL / analytics agents where correctness is verifiable | Gold set is execution-verified against a seeded brokerage DB |
| Handle non-determinism | `--runs N` repeated-run pass-consistency in `run_eval.py` |
| Fintech / brokerage domain where a wrong answer has consequences | Brokerage schema: clients, accounts, securities, orders, positions |
| Drive iteration from eval results | `system_a`'s measured failure modes are exactly what `system_b` fixes; see error analysis in the report |

## Architecture

```
data/gold.jsonl            Gold questions: question, gold_sql, category, difficulty
data/human_labels.jsonl    Human correctness labels for judge calibration
src/evalharness/
  db.py            Deterministic (seeded) brokerage SQLite database
  gold.py          Gold dataset generator (templated, >=8 question types)
  systems.py       system_a (flawed baseline) and system_b (improved) text-to-SQL
  metrics.py       Execution accuracy, normalised exact match, error categorisation
  stats.py         Wilson CI, bootstrap CI, McNemar, sample-size estimator
  judge.py         Heuristic LLM-as-judge simulation + calibration vs human labels
  run_eval.py      CLI harness: builds DB, runs systems, writes report + results.json
  regression_gate.py  CI gate vs results/baseline.json (fails on >2pp drop)
  plan.py          Sample-size planner CLI: gold-set size needed to detect
                   an accuracy improvement (delta x power grid, --from-results)
tests/             unittest suite for stats, metrics, systems, judge
results/           results.json, report.md, baseline.json (generated, checked in)
docs/DESIGN.md     Evaluation design, decisions, and limitations
```

## How to run

```bash
# 1. Run the full evaluation (builds the DB, runs both systems, 3 runs each)
python -m evalharness.run_eval --runs 3
#    (run from src/, or: PYTHONPATH=src python -m evalharness.run_eval --runs 3)

# 2. View the report
cat results/report.md

# 3. Check the regression gate against the baseline
PYTHONPATH=src python -m evalharness.regression_gate

# 4. Run the tests
PYTHONPATH=src python -m unittest discover -s tests -v

# 5. (Re)generate the gold dataset / human labels
PYTHONPATH=src python -m evalharness.gold
PYTHONPATH=src python -m evalharness.judge --write-labels
```

## Design decisions, in one paragraph

Execution accuracy is the headline metric because for text-to-SQL the
*result* is the product — two different SQL strings that return the same
answer are both right. Exact match is reported too, but as a diagnostic,
not the bar. The judge is never trusted by default: it is calibrated
against human labels first, and its disagreements are inspected, not
averaged away. A difference between two systems is not reported as a win
until a paired test (McNemar) and a confidence interval say it is more
than noise. Full reasoning and known limitations: [`docs/DESIGN.md`](docs/DESIGN.md).

## Honest limitations

The candidate systems here are rule-based generators, not LLMs — that is
deliberate. It makes every number in this repo reproducible offline with
zero dependencies, and it isolates the *evaluation methodology* (the
subject of the role) from model access. The same harness wraps an LLM by
replacing one function in `systems.py` with an API call; the gold set,
metrics, statistics, judge calibration, and regression gate are unchanged.
The judge is likewise a transparent heuristic simulation of an LLM judge,
which makes its failure modes inspectable — exactly the property the
calibration study is meant to surface.
