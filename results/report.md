# Evaluation Report — Brokerage Text-to-SQL Agent

Provenance: gold set `data/gold.jsonl` SHA-256 `e383917514ff10694b673f614d892910917f107176e181c710611bc8b9cc8ea1` · harness commit `723d57b9c12a393c074efbe53ef433be57cc5aae` — ⚠ working tree had uncommitted changes

Gold set: **65 questions** · DB seed: 42 · Runs per system: 3

## Headline results

| System | Execution accuracy | 95% Wilson CI | 95% bootstrap CI | Exact match | Pass-consistency |
|---|---|---|---|---|---|
| system_a (baseline) | 44.6% (29/65) | [0.332, 0.567] | [0.323, 0.569] | 44.6% | 0.446 |
| system_b (improved) | 100.0% (65/65) | [0.944, 1.000] | [1.000, 1.000] | 92.3% | 1.000 |

## Stratified headline accuracy

The headline accuracy above weights every question equally, so a gold set heavy in easy questions inflates it — this set has easy n=36, medium n=4, hard n=25. The stratified accuracy weights every difficulty equally instead: it is the plain mean of the per-difficulty accuracies, so no difficulty can dominate the headline by volume alone. A system that is strong only where the questions are most numerous scores lower here than in the headline; a system equally strong everywhere scores the same.

| System | Overall accuracy | Stratified accuracy | Inflation (overall − stratified) |
|---|---|---|---|
| system_a | 44.6% (29/65) | 30.1% | +14.5% |
| system_b | 100.0% (65/65) | 100.0% | +0.0% |

The stratified B − A difference is +69.9%, against +55.4% overall. When the two disagree, the stratified number is the one that survives rebalancing the gold set.

## Is the improvement real? (paired comparison)

- Accuracy difference (B − A): **+55.4%**, bootstrap 95% CI [+0.431, +0.677]
- McNemar's test (paired, same questions): b = 36 (A wrong, B right), c = 0 (A right, B wrong), p = 5.433e-09
- Verdict: the difference is **statistically significant at the 5% level**.
- To detect a further 5pp improvement over system_a with 80% power would need ~1562 gold questions per system (normal approximation) — a concrete argument for growing the gold set.

## Per-question win/loss (paired comparison)

Every question, one row: 29 both correct, 0 both wrong, 36 B only (McNemar b), 0 A only (McNemar c). Discordant questions come first — they are the whole paired difference; the rest is agreement.

| ID | Category | Difficulty | system_a | system_b | Outcome |
|---|---|---|---|---|---|
| q005 | count_by_side | easy | ✗ | ✓ | B wins |
| q006 | count_by_side | easy | ✗ | ✓ | B wins |
| q010 | count_by_country | hard | ✗ | ✓ | B wins |
| q011 | count_by_country | hard | ✗ | ✓ | B wins |
| q012 | count_by_country | hard | ✗ | ✓ | B wins |
| q013 | count_by_country | hard | ✗ | ✓ | B wins |
| q024 | avg_price_by_symbol | easy | ✗ | ✓ | B wins |
| q025 | avg_price_by_symbol | easy | ✗ | ✓ | B wins |
| q026 | avg_price_by_symbol | easy | ✗ | ✓ | B wins |
| q027 | avg_price_by_symbol | easy | ✗ | ✓ | B wins |
| q028 | avg_price_by_symbol | easy | ✗ | ✓ | B wins |
| q029 | sum_quantity_by_side_symbol | hard | ✗ | ✓ | B wins |
| q030 | sum_quantity_by_side_symbol | hard | ✗ | ✓ | B wins |
| q031 | sum_quantity_by_side_symbol | hard | ✗ | ✓ | B wins |
| q032 | sum_quantity_by_side_symbol | hard | ✗ | ✓ | B wins |
| q033 | sum_quantity_by_side_symbol | hard | ✗ | ✓ | B wins |
| q034 | sum_quantity_by_side_symbol | hard | ✗ | ✓ | B wins |
| q043 | sum_value_by_side | easy | ✗ | ✓ | B wins |
| q044 | sum_value_by_side | easy | ✗ | ✓ | B wins |
| q049 | avg_quantity_by_side | easy | ✗ | ✓ | B wins |
| q050 | avg_quantity_by_side | easy | ✗ | ✓ | B wins |
| q051 | sum_value_by_country | hard | ✗ | ✓ | B wins |
| q052 | sum_value_by_country | hard | ✗ | ✓ | B wins |
| q053 | sum_quantity_filled_by_symbol | hard | ✗ | ✓ | B wins |
| q054 | sum_quantity_filled_by_symbol | hard | ✗ | ✓ | B wins |
| q055 | sum_quantity_filled_by_symbol | hard | ✗ | ✓ | B wins |
| q056 | count_by_date_range | easy | ✗ | ✓ | B wins |
| q057 | count_by_date_range | easy | ✗ | ✓ | B wins |
| q058 | count_by_date_range | easy | ✗ | ✓ | B wins |
| q059 | count_by_date_range | easy | ✗ | ✓ | B wins |
| q060 | count_by_date_range | medium | ✗ | ✓ | B wins |
| q061 | count_by_date_range | medium | ✗ | ✓ | B wins |
| q062 | count_by_date_range | medium | ✗ | ✓ | B wins |
| q063 | count_by_date_range | medium | ✗ | ✓ | B wins |
| q064 | count_by_date_range | hard | ✗ | ✓ | B wins |
| q065 | count_by_date_range | hard | ✗ | ✓ | B wins |
| q001 | count_total | easy | ✓ | ✓ | Both correct |
| q002 | count_total | easy | ✓ | ✓ | Both correct |
| q003 | count_total | easy | ✓ | ✓ | Both correct |
| q004 | count_total | easy | ✓ | ✓ | Both correct |
| q007 | count_by_status | easy | ✓ | ✓ | Both correct |
| q008 | count_by_status | easy | ✓ | ✓ | Both correct |
| q009 | count_by_status | easy | ✓ | ✓ | Both correct |
| q014 | sum_quantity_by_symbol | easy | ✓ | ✓ | Both correct |
| q015 | sum_quantity_by_symbol | easy | ✓ | ✓ | Both correct |
| q016 | sum_quantity_by_symbol | easy | ✓ | ✓ | Both correct |
| q017 | sum_quantity_by_symbol | easy | ✓ | ✓ | Both correct |
| q018 | sum_quantity_by_symbol | easy | ✓ | ✓ | Both correct |
| q019 | sum_value_by_symbol | hard | ✓ | ✓ | Both correct |
| q020 | sum_value_by_symbol | hard | ✓ | ✓ | Both correct |
| q021 | sum_value_by_symbol | hard | ✓ | ✓ | Both correct |
| q022 | sum_value_by_symbol | hard | ✓ | ✓ | Both correct |
| q023 | sum_value_by_symbol | hard | ✓ | ✓ | Both correct |
| q035 | top_symbol_by_volume | hard | ✓ | ✓ | Both correct |
| q036 | top_symbol_by_value | hard | ✓ | ✓ | Both correct |
| q037 | top_account_by_orders | hard | ✓ | ✓ | Both correct |
| q038 | count_by_account | easy | ✓ | ✓ | Both correct |
| q039 | count_by_account | easy | ✓ | ✓ | Both correct |
| q040 | count_by_account | easy | ✓ | ✓ | Both correct |
| q041 | count_by_account | easy | ✓ | ✓ | Both correct |
| q042 | count_by_account | easy | ✓ | ✓ | Both correct |
| q045 | distinct_count | easy | ✓ | ✓ | Both correct |
| q046 | distinct_count | easy | ✓ | ✓ | Both correct |
| q047 | max_quantity | easy | ✓ | ✓ | Both correct |
| q048 | avg_quantity | easy | ✓ | ✓ | Both correct |

## Seed sensitivity

Same systems, same 65 questions, re-evaluated on 2 database seeds (42, 1234). The gold SQL is re-executed on each seed's data, so the ground truth moves with the data — what varies is only the database contents, never the questions.

| DB seed | system_a | system_b | B − A | McNemar p |
|---|---|---|---|---|
| 42 | 44.6% (29/65) | 100.0% (65/65) | +55.4% | 5.433e-09 |
| 1234 | 44.6% (29/65) | 100.0% (65/65) | +55.4% | 5.433e-09 |

Largest swing across seeds: system_a 0.0%, system_b 0.0%, B − A difference 0.0%.
Verdict: the headline metrics are **stable — every headline metric moves at most 5% across seeds, so the headline numbers are a property of the systems, not of one database draw**.

## Latency (per-question generation time, first pass)

| System | Mean | p95 |
|---|---|---|
| system_a | 0.02 ms | 0.01 ms |
| system_b | 0.01 ms | 0.01 ms |

The rule-based systems here answer in well under a millisecond, so these numbers are a floor, not a finding: they exist so that when an LLM-backed system is dropped into the same harness boundary, its latency cost shows up next to its accuracy gain instead of hiding behind it. A system that is 5 points more accurate but 100x slower is a different trade-off, and this table is where it becomes visible.

## Flaky questions (pass-consistency across repeated runs)

Each system answered every question 3 times in the repeated runs (plus the recorded first pass). A question that is right on some runs and wrong on others is flaky: its contribution to the headline accuracy is luck, not capability. For a deterministic system this list is empty — which is itself the finding. A non-deterministic system (for example an LLM-backed one) will show its wobble here first, before it shows up as noise in the headline number.

- system_a: **0 flaky questions** — every question was correct on every run or wrong on every run.
- system_b: **0 flaky questions** — every question was correct on every run or wrong on every run.

## Per-category accuracy

A category's headline percentage alone overstates how much is known when the category holds only a handful of questions: 100% on n=4 has a Wilson interval roughly [0.40, 1.00]. Read the interval, not just the point estimate — a wide interval means the category needs more questions before its accuracy can be trusted.

The B − A column is the paired difference inside the category, with its own bootstrap 95% CI: both systems answer the same questions, so this interval is narrower than the two Wilson intervals would suggest, and an interval that excludes 0 is evidence B really is better (or worse) than A *on that kind of question* — the headline difference alone cannot say where the improvement lives.

| Category | n | system_a | system_a 95% Wilson CI | system_b | system_b 95% Wilson CI | B − A | B − A 95% bootstrap CI |
|---|---|---|---|---|---|---|---|
| avg_price_by_symbol | 5 | 0% | [0.000, 0.434] | 100% | [0.566, 1.000] | +100% | [1.000, 1.000] |
| avg_quantity | 1 | 100% | [0.207, 1.000] | 100% | [0.207, 1.000] | +0% | [0.000, 0.000] |
| avg_quantity_by_side | 2 | 0% | [0.000, 0.658] | 100% | [0.342, 1.000] | +100% | [1.000, 1.000] |
| count_by_account | 5 | 100% | [0.566, 1.000] | 100% | [0.566, 1.000] | +0% | [0.000, 0.000] |
| count_by_country | 4 | 0% | [0.000, 0.490] | 100% | [0.510, 1.000] | +100% | [1.000, 1.000] |
| count_by_date_range | 10 | 0% | [0.000, 0.278] | 100% | [0.722, 1.000] | +100% | [1.000, 1.000] |
| count_by_side | 2 | 0% | [0.000, 0.658] | 100% | [0.342, 1.000] | +100% | [1.000, 1.000] |
| count_by_status | 3 | 100% | [0.438, 1.000] | 100% | [0.438, 1.000] | +0% | [0.000, 0.000] |
| count_total | 4 | 100% | [0.510, 1.000] | 100% | [0.510, 1.000] | +0% | [0.000, 0.000] |
| distinct_count | 2 | 100% | [0.342, 1.000] | 100% | [0.342, 1.000] | +0% | [0.000, 0.000] |
| max_quantity | 1 | 100% | [0.207, 1.000] | 100% | [0.207, 1.000] | +0% | [0.000, 0.000] |
| sum_quantity_by_side_symbol | 6 | 0% | [0.000, 0.390] | 100% | [0.610, 1.000] | +100% | [1.000, 1.000] |
| sum_quantity_by_symbol | 5 | 100% | [0.566, 1.000] | 100% | [0.566, 1.000] | +0% | [0.000, 0.000] |
| sum_quantity_filled_by_symbol | 3 | 0% | [0.000, 0.562] | 100% | [0.438, 1.000] | +100% | [1.000, 1.000] |
| sum_value_by_country | 2 | 0% | [0.000, 0.658] | 100% | [0.342, 1.000] | +100% | [1.000, 1.000] |
| sum_value_by_side | 2 | 0% | [0.000, 0.658] | 100% | [0.342, 1.000] | +100% | [1.000, 1.000] |
| sum_value_by_symbol | 5 | 100% | [0.566, 1.000] | 100% | [0.566, 1.000] | +0% | [0.000, 0.000] |
| top_account_by_orders | 1 | 100% | [0.207, 1.000] | 100% | [0.207, 1.000] | +0% | [0.000, 0.000] |
| top_symbol_by_value | 1 | 100% | [0.207, 1.000] | 100% | [0.207, 1.000] | +0% | [0.000, 0.000] |
| top_symbol_by_volume | 1 | 100% | [0.207, 1.000] | 100% | [0.207, 1.000] | +0% | [0.000, 0.000] |

## Exact-match gap by category

Execution accuracy says the answer is right; exact match says the SQL is the gold SQL. The gap is the questions a system got right by a different query — the same answer reached another way. A gap concentrated in one category means the gold SQL there is one of several equivalent forms, so exact-match rate understates the system there; a zero gap means that when the system is right it writes exactly the gold query. Read the gap before trusting exact match as a proxy for correctness: a system can be 100% execution-correct in a category and still show a large gap, and that is a property of the gold SQL, not a failure of the system.

| Category | n | system_a exec | system_a exact | system_a gap | system_b exec | system_b exact | system_b gap |
|---|---|---|---|---|---|---|---|
| avg_price_by_symbol | 5 | 0 (0%) | 0 (0%) | 0 (0%) | 5 (100%) | 5 (100%) | 0 (0%) |
| avg_quantity | 1 | 1 (100%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 0 (0%) |
| avg_quantity_by_side | 2 | 0 (0%) | 0 (0%) | 0 (0%) | 2 (100%) | 2 (100%) | 0 (0%) |
| count_by_account | 5 | 5 (100%) | 5 (100%) | 0 (0%) | 5 (100%) | 5 (100%) | 0 (0%) |
| count_by_country | 4 | 0 (0%) | 0 (0%) | 0 (0%) | 4 (100%) | 4 (100%) | 0 (0%) |
| count_by_date_range | 10 | 0 (0%) | 0 (0%) | 0 (0%) | 10 (100%) | 5 (50%) | 5 (50%) |
| count_by_side | 2 | 0 (0%) | 0 (0%) | 0 (0%) | 2 (100%) | 2 (100%) | 0 (0%) |
| count_by_status | 3 | 3 (100%) | 3 (100%) | 0 (0%) | 3 (100%) | 3 (100%) | 0 (0%) |
| count_total | 4 | 4 (100%) | 4 (100%) | 0 (0%) | 4 (100%) | 4 (100%) | 0 (0%) |
| distinct_count | 2 | 2 (100%) | 2 (100%) | 0 (0%) | 2 (100%) | 2 (100%) | 0 (0%) |
| max_quantity | 1 | 1 (100%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 0 (0%) |
| sum_quantity_by_side_symbol | 6 | 0 (0%) | 0 (0%) | 0 (0%) | 6 (100%) | 6 (100%) | 0 (0%) |
| sum_quantity_by_symbol | 5 | 5 (100%) | 5 (100%) | 0 (0%) | 5 (100%) | 5 (100%) | 0 (0%) |
| sum_quantity_filled_by_symbol | 3 | 0 (0%) | 0 (0%) | 0 (0%) | 3 (100%) | 3 (100%) | 0 (0%) |
| sum_value_by_country | 2 | 0 (0%) | 0 (0%) | 0 (0%) | 2 (100%) | 2 (100%) | 0 (0%) |
| sum_value_by_side | 2 | 0 (0%) | 0 (0%) | 0 (0%) | 2 (100%) | 2 (100%) | 0 (0%) |
| sum_value_by_symbol | 5 | 5 (100%) | 5 (100%) | 0 (0%) | 5 (100%) | 5 (100%) | 0 (0%) |
| top_account_by_orders | 1 | 1 (100%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 0 (0%) |
| top_symbol_by_value | 1 | 1 (100%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 0 (0%) |
| top_symbol_by_volume | 1 | 1 (100%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 0 (0%) |

Overall gap: system_a 0 of 65 (0%), system_b 5 of 65 (8%).
The gap is concentrated: 5 of system_b's 5 gap questions sit in count_by_date_range — its month questions are written with `strftime('%Y-%m', order_date)` where the gold SQL uses `BETWEEN`, the same filter in another form.

## Per-difficulty accuracy

Same reading as the per-category table: a difficulty's headline percentage alone overstates how much is known when the difficulty holds only a handful of questions. Read the interval, not just the point estimate — a wide interval means the difficulty needs more questions before its accuracy can be trusted.

| Difficulty | n | system_a | system_a 95% Wilson CI | system_b | system_b 95% Wilson CI |
|---|---|---|---|---|---|
| easy | 36 | 58% | [0.422, 0.729] | 100% | [0.904, 1.000] |
| medium | 4 | 0% | [0.000, 0.490] | 100% | [0.510, 1.000] |
| hard | 25 | 32% | [0.172, 0.516] | 100% | [0.867, 1.000] |

## Difficulty monotonicity

Accuracy should fall easy → medium → hard: harder questions should be harder. A system that scores higher on a harder difficulty than on an easier one is a warning — either the difficulty labels are wrong for those questions, or the system has a blind spot on the "easier" kind. Check the n in the table above before reading much into a gap: a violation on a 4-question cell is a handful of questions, not a pattern.

- system_a: **not monotonic** — hard 32% (n=25) beats medium 0% (n=4) by 32%.
- system_b: **monotonic** — accuracy falls easy → medium → hard as it should.

## Gold-set coverage matrix

Every category × difficulty cell should hold enough questions for its per-category and per-difficulty numbers to mean something. A cell with fewer than 3 questions is **thin**; an empty cell means that difficulty is unmeasured for that category at all. Growing the gold set should start with the empty cells, then the thin ones.

| Category | easy | medium | hard |
|---|---|---|---|
| avg_price_by_symbol | 5 | 0 ⚠ empty | 0 ⚠ empty |
| avg_quantity | 1 ⚠ thin | 0 ⚠ empty | 0 ⚠ empty |
| avg_quantity_by_side | 2 ⚠ thin | 0 ⚠ empty | 0 ⚠ empty |
| count_by_account | 5 | 0 ⚠ empty | 0 ⚠ empty |
| count_by_country | 0 ⚠ empty | 0 ⚠ empty | 4 |
| count_by_date_range | 4 | 4 | 2 ⚠ thin |
| count_by_side | 2 ⚠ thin | 0 ⚠ empty | 0 ⚠ empty |
| count_by_status | 3 | 0 ⚠ empty | 0 ⚠ empty |
| count_total | 4 | 0 ⚠ empty | 0 ⚠ empty |
| distinct_count | 2 ⚠ thin | 0 ⚠ empty | 0 ⚠ empty |
| max_quantity | 1 ⚠ thin | 0 ⚠ empty | 0 ⚠ empty |
| sum_quantity_by_side_symbol | 0 ⚠ empty | 0 ⚠ empty | 6 |
| sum_quantity_by_symbol | 5 | 0 ⚠ empty | 0 ⚠ empty |
| sum_quantity_filled_by_symbol | 0 ⚠ empty | 0 ⚠ empty | 3 |
| sum_value_by_country | 0 ⚠ empty | 0 ⚠ empty | 2 ⚠ thin |
| sum_value_by_side | 2 ⚠ thin | 0 ⚠ empty | 0 ⚠ empty |
| sum_value_by_symbol | 0 ⚠ empty | 0 ⚠ empty | 5 |
| top_account_by_orders | 0 ⚠ empty | 0 ⚠ empty | 1 ⚠ thin |
| top_symbol_by_value | 0 ⚠ empty | 0 ⚠ empty | 1 ⚠ thin |
| top_symbol_by_volume | 0 ⚠ empty | 0 ⚠ empty | 1 ⚠ thin |

Coverage: 11 of 60 cells have at least 3 questions, 11 thin, 38 empty.
Empty cells: avg_price_by_symbol / medium, avg_price_by_symbol / hard, avg_quantity / medium, avg_quantity / hard, avg_quantity_by_side / medium, avg_quantity_by_side / hard, count_by_account / medium, count_by_account / hard, count_by_country / easy, count_by_country / medium, count_by_side / medium, count_by_side / hard, count_by_status / medium, count_by_status / hard, count_total / medium, count_total / hard, distinct_count / medium, distinct_count / hard, max_quantity / medium, max_quantity / hard, sum_quantity_by_side_symbol / easy, sum_quantity_by_side_symbol / medium, sum_quantity_by_symbol / medium, sum_quantity_by_symbol / hard, sum_quantity_filled_by_symbol / easy, sum_quantity_filled_by_symbol / medium, sum_value_by_country / easy, sum_value_by_country / medium, sum_value_by_side / medium, sum_value_by_side / hard, sum_value_by_symbol / easy, sum_value_by_symbol / medium, top_account_by_orders / easy, top_account_by_orders / medium, top_symbol_by_value / easy, top_symbol_by_value / medium, top_symbol_by_volume / easy, top_symbol_by_volume / medium.
Thin cells: avg_quantity / easy (1), avg_quantity_by_side / easy (2), count_by_date_range / hard (2), count_by_side / easy (2), distinct_count / easy (2), max_quantity / easy (1), sum_value_by_country / hard (2), sum_value_by_side / easy (2), top_account_by_orders / hard (1), top_symbol_by_value / hard (1), top_symbol_by_volume / hard (1).

## Gold-set near-duplicates

1 group(s) of gold questions measure the same thing twice: they share a normalised question (same wording, different case / punctuation) or the same gold SQL under different wording. A shared gold SQL is a paraphrase — it tests robustness to phrasing, but it also double-counts one query in the headline accuracy. A shared question is a plain repeat.

| Kind | IDs | Shared text / SQL |
|---|---|---|
| gold_sql | q061, q063 | `select count(*) from orders where order_date between '2025-07-01' and '2025-09-30'` |

## Split-half reliability

The gold set is split into two interleaved halves (even- vs odd-positioned questions, so both halves span every category). If a headline accuracy is real, both halves should tell roughly the same story; if it is driven by one half of the questions, the halves diverge — and so does the B − A improvement.

| Half | n | system_a | system_b | B − A |
|---|---|---|---|---|
| Half 1 | 33 | 45.5% (15/33) | 100.0% (33/33) | +54.5% |
| Half 2 | 32 | 43.8% (14/32) | 100.0% (32/32) | +56.2% |

Half-to-half gap: system_a 1.7%, system_b 0.0%, B − A difference 1.7%.
Verdict: the split-half reliability is **balanced — every gap is within 5%, so the headline numbers are not carried by one half of the gold set**.

## Error analysis — system_a

system_a failed 36 of 65 questions. Error categories: {'wrong_filter': 25, 'wrong_join': 6, 'wrong_aggregation': 5}.

| ID | Category | Error | Candidate SQL |
|---|---|---|---|
| q005 | count_by_side | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q006 | count_by_side | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q010 | count_by_country | wrong_join | `SELECT COUNT(*) FROM orders` |
| q011 | count_by_country | wrong_join | `SELECT COUNT(*) FROM orders` |
| q012 | count_by_country | wrong_join | `SELECT COUNT(*) FROM orders` |
| q013 | count_by_country | wrong_join | `SELECT COUNT(*) FROM orders` |
| q024 | avg_price_by_symbol | wrong_aggregation | `SELECT AVG(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q025 | avg_price_by_symbol | wrong_aggregation | `SELECT AVG(quantity) FROM orders WHERE symbol = 'MSFT'` |
| q026 | avg_price_by_symbol | wrong_aggregation | `SELECT AVG(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q027 | avg_price_by_symbol | wrong_aggregation | `SELECT AVG(quantity) FROM orders WHERE symbol = 'TSLA'` |
| q028 | avg_price_by_symbol | wrong_aggregation | `SELECT AVG(quantity) FROM orders WHERE symbol = 'AMZN'` |
| q029 | sum_quantity_by_side_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q030 | sum_quantity_by_side_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q031 | sum_quantity_by_side_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'TSLA'` |
| q032 | sum_quantity_by_side_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q033 | sum_quantity_by_side_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q034 | sum_quantity_by_side_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'TSLA'` |
| q043 | sum_value_by_side | wrong_filter | `SELECT SUM(quantity * price) FROM orders` |
| q044 | sum_value_by_side | wrong_filter | `SELECT SUM(quantity * price) FROM orders` |
| q049 | avg_quantity_by_side | wrong_filter | `SELECT AVG(quantity) FROM orders` |
| q050 | avg_quantity_by_side | wrong_filter | `SELECT AVG(quantity) FROM orders` |
| q051 | sum_value_by_country | wrong_join | `SELECT SUM(quantity * price) FROM orders` |
| q052 | sum_value_by_country | wrong_join | `SELECT SUM(quantity * price) FROM orders` |
| q053 | sum_quantity_filled_by_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q054 | sum_quantity_filled_by_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'MSFT'` |
| q055 | sum_quantity_filled_by_symbol | wrong_filter | `SELECT SUM(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q056 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q057 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q058 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q059 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q060 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q061 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q062 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q063 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders` |
| q064 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders WHERE symbol = 'AAPL'` |
| q065 | count_by_date_range | wrong_filter | `SELECT COUNT(*) FROM orders WHERE symbol = 'NVDA'` |

Reading: system_a's failures are not random. They cluster exactly on questions with a side, status, country, or date-range filter, and on average-price questions — the documented weaknesses in `systems.py`. That clustering, not the headline number, is what tells engineering what to fix, and system_b is precisely that fix.

## Error-type × category cross-tab

Which error types cluster in which categories: one row per category, one column per error type, a cell counts that system's failures of that type in that category. The bold count in a row is that category's dominant error — the failure mode to fix first for that kind of question. A column that is all zeros is itself a finding: that error never happens anywhere.

### system_a (36 failures)

| Category | no_sql_generated | execution_error | empty_result | wrong_join | wrong_aggregation | wrong_filter | wrong_result | Total |
|---|---|---|---|---|---|---|---|---|
| avg_price_by_symbol | 0 | 0 | 0 | 0 | **5** | 0 | 0 | 5 |
| avg_quantity | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| avg_quantity_by_side | 0 | 0 | 0 | 0 | 0 | **2** | 0 | 2 |
| count_by_account | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| count_by_country | 0 | 0 | 0 | **4** | 0 | 0 | 0 | 4 |
| count_by_date_range | 0 | 0 | 0 | 0 | 0 | **10** | 0 | 10 |
| count_by_side | 0 | 0 | 0 | 0 | 0 | **2** | 0 | 2 |
| count_by_status | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| count_total | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| distinct_count | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| max_quantity | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sum_quantity_by_side_symbol | 0 | 0 | 0 | 0 | 0 | **6** | 0 | 6 |
| sum_quantity_by_symbol | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sum_quantity_filled_by_symbol | 0 | 0 | 0 | 0 | 0 | **3** | 0 | 3 |
| sum_value_by_country | 0 | 0 | 0 | **2** | 0 | 0 | 0 | 2 |
| sum_value_by_side | 0 | 0 | 0 | 0 | 0 | **2** | 0 | 2 |
| sum_value_by_symbol | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| top_account_by_orders | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| top_symbol_by_value | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| top_symbol_by_volume | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Dominant error per category: wrong_join dominates 2 categories (count_by_country, sum_value_by_country); wrong_aggregation dominates 1 category (avg_price_by_symbol); wrong_filter dominates 6 categories (avg_quantity_by_side, count_by_date_range, count_by_side, sum_quantity_by_side_symbol, sum_quantity_filled_by_symbol, sum_value_by_side).

- system_b: **0 failures** — nothing to cross-tabulate.

Full failure list for manual error review: `results/failures.csv` (one row per failed question, both systems).

## Judge calibration (judge vs human labels)

On 44 human-labelled answers, the heuristic judge agreed with humans 77.3% of the time: **Cohen's kappa = 0.545** (95% bootstrap CI [0.289, 0.773]) (moderate agreement), precision 0.773, recall 0.773, confusion {'tp': 17, 'fp': 5, 'fn': 5, 'tn': 17}.

Conclusion: at kappa ≈ 0.55 this judge is useful as a cheap first pass but **must not gate a release alone** — it is fooled by the right number attached to the wrong symbol/side/metric, and it rejects correct answers written in words or sensibly rounded. Execution accuracy against ground truth remains the headline metric; the judge is a supplement with known, measured limits.

### Disagreement patterns

The judge disagreed with humans on 10 labelled answers. Classified by pattern — the false positives are the judge matching the right number to the wrong thing, the false negatives are right answers its verbatim number matching cannot see:

| Pattern | Shape | Count |
|---|---|---|
| wording | false negative — correct answer written in words, no digits for the judge to match | 4 |
| wrong_scope | false positive — right number, wrong scope (country, account, or other identifier) | 2 |
| rounding | false negative — correct number sensibly rounded (e.g. 1.23 million for 1,234,500) | 1 |
| wrong_metric | false positive — right number, wrong metric (price vs quantity vs value) | 1 |
| wrong_side | false positive — right number, wrong side (BUY/SELL) | 1 |
| wrong_symbol | false positive — right number, wrong symbol | 1 |

Per disagreement: h35 (wrong_symbol), h36 (wrong_side), h37 (wrong_scope), h38 (wrong_scope), h39 (wrong_metric), h40 (wording), h41 (rounding), h42 (wording), h43 (wording), h44 (wording).

Reading: the pattern counts say where the judge's matching is blind. Wrong-symbol / wrong-side / wrong-metric false positives all come from matching a bare number with no check on what the number refers to — fixing the judge means checking the referent, not the number. Wording and rounding false negatives are the same lesson from the other side: a correct answer need not repeat the gold digits verbatim.
