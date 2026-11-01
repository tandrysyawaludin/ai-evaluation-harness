# Evaluation Report — Brokerage Text-to-SQL Agent

Gold set: **55 questions** · DB seed: 42 · Runs per system: 3

## Headline results

| System | Execution accuracy | 95% Wilson CI | 95% bootstrap CI | Exact match | Pass-consistency |
|---|---|---|---|---|---|
| system_a (baseline) | 52.7% (29/55) | [0.398, 0.653] | [0.400, 0.655] | 52.7% | 0.527 |
| system_b (improved) | 100.0% (55/55) | [0.935, 1.000] | [1.000, 1.000] | 100.0% | 1.000 |

## Is the improvement real? (paired comparison)

- Accuracy difference (B − A): **+47.3%**, bootstrap 95% CI [+0.345, +0.618]
- McNemar's test (paired, same questions): b = 26 (A wrong, B right), c = 0 (A right, B wrong), p = 9.443e-07
- Verdict: the difference is **statistically significant at the 5% level**.
- To detect a further 5pp improvement over system_a with 80% power would need ~1550 gold questions per system (normal approximation) — a concrete argument for growing the gold set.

## Per-category accuracy

| Category | n | system_a | system_b |
|---|---|---|---|
| avg_price_by_symbol | 5 | 0% | 100% |
| avg_quantity | 1 | 100% | 100% |
| avg_quantity_by_side | 2 | 0% | 100% |
| count_by_account | 5 | 100% | 100% |
| count_by_country | 4 | 0% | 100% |
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
| easy | 32 | 66% | 100% |
| hard | 23 | 35% | 100% |

## Error analysis — system_a

system_a failed 26 of 55 questions. Error categories: {'wrong_result': 26}.

| ID | Category | Error | Candidate SQL |
|---|---|---|---|
| q005 | count_by_side | wrong_result | `SELECT COUNT(*) FROM orders` |
| q006 | count_by_side | wrong_result | `SELECT COUNT(*) FROM orders` |
| q010 | count_by_country | wrong_result | `SELECT COUNT(*) FROM orders` |
| q011 | count_by_country | wrong_result | `SELECT COUNT(*) FROM orders` |
| q012 | count_by_country | wrong_result | `SELECT COUNT(*) FROM orders` |
| q013 | count_by_country | wrong_result | `SELECT COUNT(*) FROM orders` |
| q024 | avg_price_by_symbol | wrong_result | `SELECT AVG(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q025 | avg_price_by_symbol | wrong_result | `SELECT AVG(quantity) FROM orders WHERE symbol = 'MSFT'` |
| q026 | avg_price_by_symbol | wrong_result | `SELECT AVG(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q027 | avg_price_by_symbol | wrong_result | `SELECT AVG(quantity) FROM orders WHERE symbol = 'TSLA'` |
| q028 | avg_price_by_symbol | wrong_result | `SELECT AVG(quantity) FROM orders WHERE symbol = 'AMZN'` |
| q029 | sum_quantity_by_side_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q030 | sum_quantity_by_side_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q031 | sum_quantity_by_side_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'TSLA'` |
| q032 | sum_quantity_by_side_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q033 | sum_quantity_by_side_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'NVDA'` |
| q034 | sum_quantity_by_side_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'TSLA'` |
| q043 | sum_value_by_side | wrong_result | `SELECT SUM(quantity * price) FROM orders` |
| q044 | sum_value_by_side | wrong_result | `SELECT SUM(quantity * price) FROM orders` |
| q049 | avg_quantity_by_side | wrong_result | `SELECT AVG(quantity) FROM orders` |
| q050 | avg_quantity_by_side | wrong_result | `SELECT AVG(quantity) FROM orders` |
| q051 | sum_value_by_country | wrong_result | `SELECT SUM(quantity * price) FROM orders` |
| q052 | sum_value_by_country | wrong_result | `SELECT SUM(quantity * price) FROM orders` |
| q053 | sum_quantity_filled_by_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'AAPL'` |
| q054 | sum_quantity_filled_by_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'MSFT'` |
| q055 | sum_quantity_filled_by_symbol | wrong_result | `SELECT SUM(quantity) FROM orders WHERE symbol = 'NVDA'` |

Reading: system_a's failures are not random. They cluster exactly on questions with a side, status, or country filter, and on average-price questions — the documented weaknesses in `systems.py`. That clustering, not the headline number, is what tells engineering what to fix, and system_b is precisely that fix.

## Judge calibration (judge vs human labels)

On 44 human-labelled answers, the heuristic judge agreed with humans 77.3% of the time: **Cohen's kappa = 0.545** (95% bootstrap CI [0.289, 0.773]) (moderate agreement), precision 0.773, recall 0.773, confusion {'tp': 17, 'fp': 5, 'fn': 5, 'tn': 17}.

Conclusion: at kappa ≈ 0.55 this judge is useful as a cheap first pass but **must not gate a release alone** — it is fooled by the right number attached to the wrong symbol/side/metric, and it rejects correct answers written in words or sensibly rounded. Execution accuracy against ground truth remains the headline metric; the judge is a supplement with known, measured limits.
