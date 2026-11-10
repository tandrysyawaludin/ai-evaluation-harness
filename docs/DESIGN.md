# Evaluation Design

## 1. Ground truth philosophy

Ground truth is **execution against data**, not a reference string. Each gold
item carries a natural-language question and a `gold_sql` query whose result
on the seeded database *is* the answer. The database generator is seeded
(seed 42), so ground truth is stable and reproducible across machines and runs.

Gold questions are templated across at least eight question types (counts,
sums, traded value, averages, top-N, and filters by side / status / country /
account) at two difficulty levels. Templates are a starting point, not the
finish line: in production the gold set should be grown from real user
questions, double-labelled, and versioned, with disagreements adjudicated
and recorded. A gold set nobody has argued about is a gold set nobody has read.

Principles:
- **Verifiable first.** Prefer questions whose correctness can be checked
  against data over questions graded by taste.
- **Stratified, not just large.** Report accuracy per category; an aggregate
  can hide a system that is perfect on counts and broken on filters.
- **Frozen for comparisons.** A/B numbers are only comparable on the same
  gold-set version and the same database seed.

## 2. Metrics

- **Execution accuracy (headline).** Candidate SQL and gold SQL are both
  executed; results are compared as *unordered* row sets with floats rounded
  to 4 decimal places. Row order is not meaning for these questions
  (except where the question asks for a ranking, which is encoded by a
  single-row top-N result).
- **Normalised exact match (diagnostic).** SQL strings compared after
  lower-casing, whitespace collapsing, and semicolon stripping. A system can
  be execution-correct and exact-match-wrong — that gap measures stylistic
  divergence, not error.
- **Error categorisation.** Every failure is bucketed: `execution_error`
  (SQL raised), `empty_result`, `no_sql_generated`, or — when the result
  is wrong but non-empty — `wrong_join`, `wrong_aggregation`,
  `wrong_filter`, or generic `wrong_result`. The finer buckets are
  assigned by comparing candidate and gold SQL: joined tables, aggregate
  calls plus GROUP BY, then WHERE conjuncts (order-insensitive), in that
  priority order. A failure that matches on all three stays generic,
  e.g. a wrong SELECT column, ORDER BY, or LIMIT. Error analysis drives
  iteration; a single accuracy number does not. Every failure is also
  exported to `results/failures.csv` — one row per failed question per
  system (question, category, difficulty, error, candidate SQL, gold
  SQL, exact match, latency) — so a human can triage the errors in a
  spreadsheet without re-running the eval or digging through
  `results.json`.
- **Latency.** Every question records the time spent inside the system
  function (generation time, not SQL execution time); the harness reports
  mean and p95 per system, in the console output, `results.json`, and the
  report. Accuracy without latency hides the cost of an improvement.

## 3. Statistics: evals are experiments

- **Wilson score interval** for each system's accuracy — better coverage
  than the normal approximation at small n and near 0/1.
- **Bootstrap CI** (seeded RNG, percentile method) for accuracy and for the
  A−B difference, as a non-parametric cross-check.
- **McNemar's test** for the A/B comparison, because the systems are
  evaluated on the *same* questions: the data are paired, and an unpaired
  test would throw that information away. We report the discordant counts
  (b, c) alongside the p-value so the test is auditable — and the report
  carries the full per-question win/loss table (both correct, both wrong,
  A only, B only, discordant questions first), so every discordant count
  traces to named questions.
- **Sample-size estimator** (normal approximation for two proportions) so
  "how many gold questions do we need to detect a 5-point improvement?"
  has a number, not a shrug.

## 4. Judge calibration

An automated judge (here, a transparent heuristic simulating an LLM judge
grading natural-language answers) is a *measurement instrument*, and
instruments get calibrated before use:

- A human-labelled set (≥30 examples, deliberately including cases where a
  naive judge is fooled — e.g. the right number attached to the wrong
  symbol, or the right answer in words instead of digits).
- Agreement with humans: **Cohen's kappa**, plus judge **precision/recall**
  for the "correct" class and a full **confusion matrix**.
- Disagreements are data. They are listed and inspected; a judge with
  kappa below ~0.6 should not gate a release, whatever its raw accuracy.

## 5. Non-determinism

Real model systems do not always answer the same way twice. The harness
therefore supports `--runs N`: each system answers each question N times,
and we report **pass-consistency** (mean fraction of runs that are
execution-correct, and the share of questions correct on *every* run).
The rule-based systems in this repo are deterministic, so their consistency
is 1.0 — the machinery is what matters, and it is exercised by the tests
and the CLI so an LLM-backed system can be dropped in unchanged.

A second, orthogonal source of noise is the database itself: the same
systems on a different seeded database can score differently even with
identical questions, because the data the questions run against changed.
The harness therefore evaluates under two seeds by default (42 and 1234;
`--seeds` overrides) and reports the largest swing of each headline
metric across seeds, with a **stable** verdict when every swing is at
most 5pp. Ground truth stays fair across seeds because each gold SQL is
re-executed on that seed's data. The primary seed's full results remain
the top-level `systems` block, so the regression gate and `--compare`
are unaffected; the per-seed headline numbers live in
`seed_sensitivity` in `results.json` and in the report.

## 6. Regression gates

`results/baseline.json` records the accepted execution accuracy for the
reference system. `regression_gate.py` fails (exit 1) if a new results file
drops more than **2 percentage points** below baseline. Two points is a
policy choice: tight enough to catch real regressions on a gold set of this
size, loose enough not to flap on judge/sampling noise. In CI the gate runs
on every push, after the unit tests and a fresh evaluation.

## 7. Limitations

- Rule-based candidate systems, not LLMs (see README — deliberate, for
  offline reproducibility; the harness boundary is one function).
- Templated gold questions understate the linguistic diversity of real
  users. The mitigation path is logging real questions into the gold set.
- SQLite dialect only; production text-to-SQL evals should also check
  dialect portability and query cost / safety (e.g. full-table scans,
  write statements), which are out of scope here.
- The heuristic judge simulates an LLM judge's *failure modes*; it is not
  a substitute for calibrating a real LLM judge on real model outputs.
