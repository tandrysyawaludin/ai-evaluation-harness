# Evaluation Report — Brokerage Text-to-SQL Agent

Gold set: **65 questions** · DB seed: 42 · Runs per system: 3

## Headline results

| System | Execution accuracy | 95% Wilson CI | 95% bootstrap CI | Exact match | Pass-consistency |
|---|---|---|---|---|---|
| system_a (baseline) | 44.6% (29/65) | [0.332, 0.567] | [0.323, 0.569] | 44.6% | 0.446 |
| system_b (improved) | 100.0% (65/65) | [0.944, 1.000] | [1.000, 1.000] | 92.3% | 1.000 |

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

## Per-category accuracy

| Category | n | system_a | system_b |
|---|---|---|---|
| avg_price_by_symbol | 5 | 0% | 100% |
| avg_quantity | 1 | 100% | 100% |
| avg_quantity_by_side | 2 | 0% | 100% |
| count_by_account | 5 | 100% | 100% |
| count_by_country | 4 | 0% | 100% |
| count_by_date_range | 10 | 0% | 100% |
| count_by_side | 2 | 0% | 100% |
| count_by_status | 3 | 100% | 100% |
| count_total | 4 | 100% | 100% |
| distinct_count | 2 | 100% | 100% |
| max_quantity | 1 | 100% | 100% |
| sum_quantity_by_side_symbol | 6 | 0% | 100% |
| sum_quantity_by_symbol | 5 | 100% | 100% |
| sum_quantity_filled_by_symbol | 3 | 0% | 100% |
| sum_value_by_country | 2 | 0% | 100% |
| sum_value_by_side | 2 | 0% | 100% |
| sum_value_by_symbol | 5 | 100% | 100% |
| top_account_by_orders | 1 | 100% | 100% |
| top_symbol_by_value | 1 | 100% | 100% |
| top_symbol_by_volume | 1 | 100% | 100% |

## Per-difficulty accuracy

| Difficulty | n | system_a | system_b |
|---|---|---|---|
| easy | 36 | 58% | 100% |
| medium | 4 | 0% | 100% |
| hard | 25 | 32% | 100% |

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

Full failure list for manual error review: `results/failures.csv` (one row per failed question, both systems).

## Judge calibration (judge vs human labels)

On 44 human-labelled answers, the heuristic judge agreed with humans 77.3% of the time: **Cohen's kappa = 0.545** (95% bootstrap CI [0.289, 0.773]) (moderate agreement), precision 0.773, recall 0.773, confusion {'tp': 17, 'fp': 5, 'fn': 5, 'tn': 17}.

Conclusion: at kappa ≈ 0.55 this judge is useful as a cheap first pass but **must not gate a release alone** — it is fooled by the right number attached to the wrong symbol/side/metric, and it rejects correct answers written in words or sensibly rounded. Execution accuracy against ground truth remains the headline metric; the judge is a supplement with known, measured limits.
