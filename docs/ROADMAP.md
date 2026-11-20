# Roadmap

One small, verified improvement at a time. Each item ships as a single
commit with tests passing and the regression gate green.

## Queue

- [x] Bootstrap confidence interval for the judge's Cohen's kappa, with tests
- [x] Per-difficulty breakdown (easy / medium / hard) in the eval report
- [x] New gold category: date-range questions over orders
- [x] Per-system latency measurement (mean / p95) in harness output and report
- [x] Sample-size planner CLI built on the existing estimator in stats.py
- [x] Schema validation for gold.jsonl and human_labels.jsonl, with tests
- [x] Finer error taxonomy: separate wrong-filter, wrong-aggregation and
      wrong-join failures from generic wrong-result where determinable
- [x] `--compare` mode in run_eval that diffs two results.json files
- [x] Seed-sensitivity run: evaluate under a second database seed and
      report how stable the headline metrics are
- [x] Failures export (CSV) for manual error review
- [x] Per-question win/loss table for the paired system comparison in the report
- [x] Evaluation guidelines document: how to add questions, label answers,
      and review judge disagreements (extends docs/DESIGN.md)
- [x] Flaky-question report: per-question pass-consistency across the
      repeated runs, listing questions correct on some runs but not all,
      in results.json and report.md, with tests
- [x] Gold-set coverage matrix: category × difficulty counts in the report,
      flagging empty or thin (< 3 questions) cells, with tests
- [x] Split-half reliability: split the gold set into two halves and report
      per-system accuracy per half, so a headline number driven by one
      half is visible, with tests
- [x] Judge disagreement pattern summary: classify judge-vs-human
      disagreements by pattern (right number on the wrong symbol/side/
      metric vs wording/rounding) and report the counts, with tests
- [x] Error-type × category cross-tab in the report: which error types
      cluster in which categories, with tests
- [x] Near-duplicate gold questions: flag groups sharing a normalised
      question or the same gold SQL, in results.json and the report,
      with tests
- [x] Difficulty-monotonicity check: flag when per-difficulty accuracy
      does not fall easy → medium → hard, in the report, with tests
- [x] Results provenance: record the gold-set hash and harness git
      commit in results.json and the report header, with tests
- [x] `--category` filter flag: run the eval on a subset of gold
      categories for targeted iteration, with tests
- [ ] Per-category Wilson 95% CIs in the per-category accuracy table,
      with tests

## Done

- [x] Evaluation guidelines, metrics, judge calibration, regression gate,
      CI — see git history and docs/DESIGN.md
