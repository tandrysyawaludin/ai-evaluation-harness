# Evaluation Guidelines

Practical rules for growing and maintaining this harness's ground truth.
The design rationale lives in [`docs/DESIGN.md`](DESIGN.md); this document
is the operating manual — what to do, in what order, and what "done" looks
like. The gold set and the human labels are the ground truth everything
else is measured against, so changes here are held to a higher bar than
changes anywhere else in the repo.

## 1. Adding gold questions

### 1.1 Schema

One JSON object per line in `data/gold.jsonl`:

```json
{"id": "q066", "question": "How many orders were placed in January 2026?",
 "gold_sql": "SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01' AND order_date < '2026-02-01'",
 "category": "count_by_date_range", "difficulty": "medium"}
```

- `id`: `q` followed by the next free number (`q001`–`q065` are taken).
  Ids are never reused, even if a question is retired — a retired id stays
  retired so old results stay interpretable.
- `question`: natural language, unambiguous, answerable from the seeded
  database alone. If two reasonable people would read it two ways, rewrite
  it until they cannot.
- `gold_sql`: a single `SELECT` statement, no semicolons, one `FROM`
  clause, referencing only the known tables (`clients`, `accounts`,
  `securities`, `orders`, `positions`). It must return the answer when
  executed on the seeded database — execution against data *is* the ground
  truth, so a gold SQL that errors or returns the wrong rows is a wrong
  answer, not a formatting nit.
- `category`: a short snake_case name for the question type. Reuse an
  existing category when the question is a new instance of it; create a new
  one only when the question exercises something no existing category does.
  (65 questions across 20 categories as of this writing.)
- `difficulty`: `easy`, `medium`, or `hard`.
  - **easy** — one table, one aggregate or filter (e.g. a total count).
  - **medium** — two filters, one join, or a date range.
  - **hard** — a multi-table join, a `GROUP BY` with `ORDER BY`/`LIMIT`
    (top-N), or two filters combined with an aggregate.

### 1.2 How to add them

1. Prefer adding a template to the generator (`src/evalharness/gold.py`)
   and regenerating `data/gold.jsonl`, so the new questions stay
   reproducible from code. Hand-appending a line to `gold.jsonl` is
   acceptable for one-off questions taken from real users, but then the
   question exists only in the data file — say so in the commit message.
2. Run the validator before anything else:
   `PYTHONPATH=src python -m evalharness.validate`
   It rejects missing or unknown fields, duplicate ids or question text,
   bad difficulty values, non-`SELECT` gold SQL, and unknown tables. The
   harness runs this check before every evaluation, so a bad row fails
   loudly instead of silently skewing results.
3. Run the full harness (`PYTHONPATH=src python -m evalharness.run_eval
   --runs 3`) and the regression gate. A new question that every system
   gets wrong is not automatically a bad question — but it is a question
   to look at: check the gold SQL by hand before assuming the systems
   are at fault.
4. Record the change in the commit message (how many questions added,
   which category, why).

### 1.3 Growing from real questions

Templated questions understate how real users ask things. When a real
question arrives (a log, a support thread, a colleague's phrasing):

- Keep the user's wording where it is unambiguous; paraphrase only to
  remove ambiguity, and keep the original wording in the commit message
  so the paraphrase is auditable.
- Write the gold SQL first, run it, and read the result before writing
  the question down — if the result is not what the question seems to
  ask, the question is ambiguous.
- Add the question to a category that already exists when possible, so
  per-category accuracy stays comparable; a new category with one
  question tells you nothing until it has several.

### 1.4 Frozen for comparisons

A/B numbers are only comparable on the same gold-set version and the same
database seed. Adding, removing, or editing a gold question changes the
gold set, so:

- Never edit a gold question in place to make a system look better.
  If a question is wrong, fix the gold SQL (or retire the question) and
  say so in the commit message; the accuracy numbers before and after
  the fix are not comparable.
- When comparing two systems, run both on the same checkout. The
  `--compare` mode diffs two `results.json` files, but it cannot rescue
  a comparison run on different gold sets.

## 2. Labelling answers (judge calibration set)

### 2.1 Schema

One JSON object per line in `data/human_labels.jsonl`:

```json
{"id": "h45", "gold_answer": "360 orders were placed in total.",
 "candidate_answer": "There were 360 orders in total.", "human_label": "correct"}
```

- `id`: `h` followed by the next free number (`h01`–`h44` are taken).
- `gold_answer`: the correct answer in natural language.
- `candidate_answer`: the answer being judged.
- `human_label`: `correct` or `incorrect` — the human verdict, which is
  the ground truth the judge is measured against.

### 2.2 What a good label set looks like

- **At least 30 examples**, balanced between `correct` and `incorrect`
  (the current set is 44: 22 correct, 22 incorrect). A set of 30
  all-correct answers calibrates nothing.
- **Deliberately include cases where a naive judge is fooled.** The
  current set has 10 designed disagreement cases (5 false positives, 5
  false negatives): the right number attached to the wrong symbol, side,
  or metric; the right answer written in words instead of digits; a
  sensibly rounded number. Every new batch of labels should add at least
  one such trap — a judge that is only tested on easy cases is not
  tested.
- **Label the answer, not the SQL.** The judge grades natural-language
  answers; a candidate answer that is right in substance but phrased
  differently is `correct`. A candidate that quotes the right number
  for the wrong thing is `incorrect`, however confident it sounds.

### 2.3 Double-labelling and adjudication

- Every new label is read by a second person before it is committed.
  If the two labellers disagree, the pair is discussed and the agreed
  verdict recorded; if no agreement is reached, the pair is dropped
  rather than labelled by coin flip. A label set nobody has argued
  about is a label set nobody has read.
- The generator (`src/evalharness/judge.py`, `build_human_labels`)
  produces the checked-in `data/human_labels.jsonl`. Add new pairs
  there so the file stays regenerable, in the same style as the
  existing correct / incorrect / false-positive / false-negative groups.
- Run the validator after any change; it checks the label schema the
  same way it checks the gold set.

## 3. Reviewing judge disagreements

### 3.1 Where disagreements surface

Every harness run calibrates the judge against the human labels and
reports, in the console output, `results.json` (`judge_calibration`),
and `results/report.md`:

- **Cohen's kappa** with a bootstrap 95% CI, plus agreement rate,
  precision/recall for the `correct` class, and the full confusion
  matrix (`tp`/`fp`/`fn`/`tn`).
- The **disagreements list**: every labelled answer where the judge and
  the human differ, with the gold answer, the candidate answer, and
  both verdicts.

Current state, for reference: on 44 labels the heuristic judge agrees
with humans 77.3% of the time, kappa = 0.545 (95% CI [0.289, 0.773]),
confusion `tp 17 / fp 5 / fn 5 / tn 17`. That is moderate agreement —
useful as a cheap first pass, not a release gate on its own.

### 3.2 The review loop

1. **Read every disagreement.** There are few enough that skimming is
   not acceptable; each one is either a judge bug, a bad label, or a
   genuinely hard case, and you cannot tell which without reading it.
2. **Classify it:**
   - *False positive* (judge says correct, human says incorrect) —
     usually the judge matched a number and ignored what the number
     refers to (wrong symbol, side, or metric). Fix the judge, or add
     a label pair that pins the distinction down.
   - *False negative* (judge says incorrect, human says correct) —
     usually the answer is right but phrased in words, rounded, or
     reordered. Fix the judge's matching, not the label — unless the
     answer is genuinely ambiguous, in which case fix the label.
   - *Bad label* — the human verdict was wrong. Correct it, note it in
     the commit message, and re-run calibration. Labels are ground
     truth, but ground truth written by humans can be wrong.
3. **Re-run calibration** (`PYTHONPATH=src python -m evalharness.run_eval
   --runs 3`) and check kappa moved in the right direction. A judge
   change that fixes one disagreement and creates two new ones is not
   a fix.
4. **Record the decision.** The commit message for a judge change names
   the disagreement(s) it addresses; the commit message for a label
   change names the label id(s) and why the verdict changed.

### 3.3 When the judge may gate a release

- **Kappa below ~0.6: the judge must not gate a release**, whatever its
  raw accuracy. At that level the judge disagrees with humans often
  enough that its verdict is not a reliable proxy for correctness.
- **Kappa at or above ~0.6:** the judge may be used as a first-pass
  filter, with execution accuracy against ground truth remaining the
  headline metric and the final call made by a human reading the
  disagreements.
- A kappa that drops after a change to the judge or the label set is a
  regression: investigate before merging, the same way a drop in
  execution accuracy would be investigated.

## 4. Checklist before merging a ground-truth change

- [ ] Validator passes (`PYTHONPATH=src python -m evalharness.validate`).
- [ ] New gold questions: gold SQL executed by hand and result read.
- [ ] New labels: second person has read them; disagreements adjudicated.
- [ ] Full harness run passes (`--runs 3`) and the regression gate is green.
- [ ] Commit message states what changed in the ground truth and why —
      never silently, never bundled with an unrelated change.
