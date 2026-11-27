"""LLM-as-judge simulation and calibration against human labels.

An automated judge is a measurement instrument: it must be calibrated
against human ground truth before its scores are trusted. This module
provides a transparent heuristic judge (simulating an LLM judge grading
natural-language answers derived from query results), a human-labelled
dataset, and calibration metrics: Cohen's kappa, precision/recall, and
a confusion matrix.

The labelled set deliberately includes cases where a naive judge is
fooled, in both directions:
  * false positives — the gold number appears, but attached to the wrong
    symbol / side, or as a coincidental figure in a longer wrong answer;
  * false negatives — the answer is correct but written in words, or
    sensibly rounded, so exact number matching fails.
"""
import json
import os
import random
import re
from collections import Counter


def _numbers(text):
    out = []
    for tok in re.findall(r"\$?([\d,]+(?:\.\d+)?)", text or ""):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def judge(gold_answer, candidate_answer):
    """Heuristic judge: 'correct' if the gold headline number (the final
    number in the gold answer — earlier numbers are usually identifiers
    such as account ids) appears verbatim among the candidate's numbers.
    Naive by design — its failure modes are the subject of the
    calibration study."""
    gold_nums = _numbers(gold_answer)
    cand_nums = _numbers(candidate_answer)
    if not gold_nums or not cand_nums:
        return "incorrect"
    return "correct" if gold_nums[-1] in cand_nums else "incorrect"


# Disagreement patterns: the recurring shapes a judge-vs-human
# disagreement takes. False positives are the judge matching the right
# number to the wrong thing; false negatives are a right answer the
# judge's verbatim number matching cannot see. `other` is the honest
# fallback — a disagreement that fits none of the named shapes still
# counts, so the pattern counts always add up to the disagreement total.
DISAGREEMENT_PATTERNS = {
    "wrong_symbol": "false positive — right number, wrong symbol",
    "wrong_side": "false positive — right number, wrong side (BUY/SELL)",
    "wrong_metric": "false positive — right number, wrong metric "
                    "(price vs quantity vs value)",
    "wrong_scope": "false positive — right number, wrong scope "
                   "(country, account, or other identifier)",
    "wording": "false negative — correct answer written in words, "
               "no digits for the judge to match",
    "rounding": "false negative — correct number sensibly rounded "
                "(e.g. 1.23 million for 1,234,500)",
    "other": "disagreement fitting none of the named patterns",
}

_SIDES = ("BUY", "SELL")
_METRIC_WORDS = {"price", "quantity", "value", "orders", "accounts",
                 "clients", "symbols", "shares", "trades"}
_COUNTRIES = {"japan", "canada", "usa", "united states", "uk", "germany",
              "france", "china", "india", "australia", "singapore",
              "korea", "brazil", "mexico", "netherlands"}
_NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven",
                 "eight", "nine", "ten", "eleven", "twelve", "thirteen",
                 "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                 "nineteen", "twenty", "thirty", "forty", "fifty", "sixty",
                 "seventy", "eighty", "ninety"}
# Scale words are not counting words on their own: "1.1 million" is a
# rescaled digit, not a spelled-out number. They only signal wording
# when the candidate has no digits at all ("a million orders").
_SCALE_WORDS = {"hundred", "thousand", "million", "billion"}


def _symbols(text):
    """Ticker symbols mentioned: any all-caps token of ticker length
    that is not a trade side."""
    return {t for t in re.findall(r"[A-Z]{2,5}", text or "")
            if t not in _SIDES}


def _words(text):
    return re.findall(r"[A-Za-z]+|[\d,]+(?:\.\d+)?", text or "")


def _nearest_side(text, number):
    """The BUY/SELL word closest to the headline number in the text.

    The side that matters is the one attached to the number the judge
    matched, not just any side mentioned anywhere in the answer:
    "185 SELL orders and 90 BUY orders" is a wrong-side answer even
    though BUY appears in it. Returns None when no side is mentioned.
    """
    tokens = _words(text)
    try:
        idx = next(i for i, t in enumerate(tokens)
                   if _numbers(t) and _numbers(t)[0] == number)
    except StopIteration:
        return None
    sides = [(i, t) for i, t in enumerate(tokens) if t in _SIDES]
    if not sides:
        return None
    return min(sides, key=lambda p: abs(p[0] - idx))[1]


def _metric_words(text):
    return {w.lower() for w in _words(text)} & _METRIC_WORDS


def _account_id(text):
    m = re.search(r"\baccount\s+(\d+)", text or "", re.IGNORECASE)
    return m.group(1) if m else None


def _countries(text):
    return {w.lower() for w in _words(text)} & _COUNTRIES


def _number_words(text):
    return {w.lower() for w in _words(text)} & _NUMBER_WORDS


def _scale_words(text):
    return {w.lower() for w in _words(text)} & _SCALE_WORDS


def _is_rounded_form(candidate_number, gold_number):
    """True when the candidate number is the gold number rounded, or
    rounded and rescaled (thousands / millions / billions): 1.23 for
    1,234,500, 54 for 54.2. A 1% relative tolerance is the "sensibly
    rounded" bound — wider than that and it is a different number."""
    if gold_number == 0:
        return candidate_number == 0
    for scale in (1, 1e3, 1e6, 1e9):
        if abs(candidate_number * scale - gold_number) <= 0.01 * abs(gold_number):
            return True
    return False


def classify_disagreement(gold_answer, candidate_answer,
                          human_label, judge_label):
    """Classify one judge-vs-human disagreement by pattern.

    Returns None when the judge and the human agree — there is no
    disagreement to classify. Direction comes from the labels:
    judge "correct" vs human "incorrect" is a false positive (the
    right number attached to the wrong symbol / side / metric /
    scope); judge "incorrect" vs human "correct" is a false
    negative (wording or rounding). Anything that fits neither shape
    is "other", never silently dropped.
    """
    if human_label == judge_label:
        return None
    gold_nums = _numbers(gold_answer)
    cand_nums = _numbers(candidate_answer)
    headline = gold_nums[-1] if gold_nums else None
    if judge_label == "correct":
        # False positive: the gold headline number is in the candidate,
        # so what the number refers to must be what differs.
        if _symbols(gold_answer) != _symbols(candidate_answer):
            return "wrong_symbol"
        if headline is not None and (
                _nearest_side(gold_answer, headline)
                != _nearest_side(candidate_answer, headline)):
            return "wrong_side"
        if _metric_words(gold_answer) != _metric_words(candidate_answer):
            return "wrong_metric"
        gold_acct, cand_acct = _account_id(gold_answer), _account_id(candidate_answer)
        if gold_acct and cand_acct and gold_acct != cand_acct:
            return "wrong_scope"
        if _countries(gold_answer) != _countries(candidate_answer):
            return "wrong_scope"
        return "other"
    # False negative: the gold number is not verbatim in the candidate,
    # yet the human says the answer is right. Rounding is checked
    # before wording: "about 1.23 million" contains the word "million"
    # but is a rounded number, not a number written out in words.
    # Wording also covers answers where the headline number is in
    # words while other figures stay digits ("Account 5 placed
    # twenty orders") — the judge's digits say nothing about the
    # headline figure there.
    if headline is not None and any(
            _is_rounded_form(n, headline) for n in cand_nums):
        return "rounding"
    if _number_words(candidate_answer) or (
            not cand_nums and _scale_words(candidate_answer)):
        return "wording"
    return "other"


def cohens_kappa(pairs):
    """Cohen's kappa for (human, judge) label pairs over two classes."""
    n = len(pairs)
    if n == 0:
        return 0.0
    labels = ["correct", "incorrect"]
    observed = sum(1 for h, j in pairs if h == j) / n
    expected = 0.0
    for lab in labels:
        p_h = sum(1 for h, _ in pairs if h == lab) / n
        p_j = sum(1 for _, j in pairs if j == lab) / n
        expected += p_h * p_j
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def kappa_bootstrap_ci(pairs, n_boot=2000, seed=123, alpha=0.05):
    """Percentile bootstrap CI for Cohen's kappa.

    Resamples the (human, judge) pairs with replacement, recomputes
    kappa on each resample, and returns the central (1 - alpha)
    percentile interval. Seeded, so the interval is reproducible.
    With only 44 labelled answers the point estimate alone overstates
    how precisely the judge's agreement is known — the interval is the
    honest version of the number. Returns (0.0, 0.0) for no pairs.
    """
    if not pairs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(pairs)
    stats = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        stats.append(cohens_kappa(sample))
    stats.sort()
    lo = stats[int((alpha / 2) * n_boot)]
    hi = stats[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return (lo, hi)


ANSWER_TYPES = ("numeric", "text")


def answer_type(gold_answer):
    """'numeric' when the gold answer states its headline as digits,
    'text' when it contains no digits at all — a name, symbol, status
    or country. The type is a property of the answer, not of the
    candidate's phrasing: 'twenty orders' as a candidate for a numeric
    gold answer is still a numeric answer, just worded. A
    number-matching judge can only ever grade numeric answers, so the
    split is what makes that blind spot measurable."""
    return "numeric" if _numbers(gold_answer) else "text"


def _calibration_stats(pairs):
    """Agreement, kappa, precision/recall and confusion for one set of
    (human, judge) label pairs. Shared by the overall calibration and
    the per-answer-type splits so the two can never drift apart."""
    n = len(pairs)
    tp = sum(1 for h, j in pairs if h == "correct" and j == "correct")
    fp = sum(1 for h, j in pairs if h == "incorrect" and j == "correct")
    fn = sum(1 for h, j in pairs if h == "correct" and j == "incorrect")
    tn = sum(1 for h, j in pairs if h == "incorrect" and j == "incorrect")
    return {
        "n": n,
        "agreement": sum(1 for h, j in pairs if h == j) / n if n else 0.0,
        "cohens_kappa": cohens_kappa(pairs),
        "precision_correct": tp / (tp + fp) if (tp + fp) else 0.0,
        "recall_correct": tp / (tp + fn) if (tp + fn) else 0.0,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def calibrate(labels):
    """labels: list of dicts with gold_answer, candidate_answer, human_label."""
    pairs, rows = [], []
    pairs_by_type = {t: [] for t in ANSWER_TYPES}
    for item in labels:
        verdict = judge(item["gold_answer"], item["candidate_answer"])
        human = item["human_label"]
        pairs.append((human, verdict))
        pairs_by_type[answer_type(item["gold_answer"])].append((human, verdict))
        agree = verdict == human
        rows.append({**item, "judge_label": verdict, "agree": agree})
    stats = _calibration_stats(pairs)
    disagreements = [r for r in rows if not r["agree"]]
    for d in disagreements:
        d["pattern"] = classify_disagreement(
            d["gold_answer"], d["candidate_answer"],
            d["human_label"], d["judge_label"])
    pattern_counts = dict(Counter(d["pattern"] for d in disagreements))
    # Per-answer-type split: no bootstrap CI per type. With only a
    # handful of text labels an interval would be noise dressed as
    # precision; the split is a diagnostic — a judge good on numbers
    # and blind on words must show up as a gap, not as two intervals.
    return {
        **stats,
        "cohens_kappa_bootstrap_95ci": kappa_bootstrap_ci(pairs),
        "by_answer_type": {t: _calibration_stats(pairs_by_type[t])
                           for t in ANSWER_TYPES},
        "disagreements": disagreements,
        "disagreement_patterns": {
            "total": len(disagreements),
            "counts": pattern_counts,
        },
    }


def build_human_labels():
    """48 human-labelled examples: 36 the naive judge gets right,
    12 designed disagreement cases (5 false positives, 7 false
    negatives). The last four are text answers — gold answers with no
    digits at all (a symbol, a status, a country) — so the calibration
    split by answer type has a real text side: a number-matching judge
    can never mark a text answer 'correct', and the two correct text
    answers are false negatives by construction."""
    labels = []

    def add(gold, cand, human):
        labels.append({"id": f"h{len(labels)+1:02d}", "gold_answer": gold,
                       "candidate_answer": cand, "human_label": human})

    # --- straightforward correct answers (judge agrees) ---
    correct_pairs = [
        ("360 orders were placed in total.", "There were 360 orders in total."),
        ("The total quantity traded for AAPL was 4,250.", "AAPL total quantity: 4,250."),
        ("There were 185 BUY orders.", "185 BUY orders were placed."),
        ("The average price for MSFT was 421.55.", "MSFT averaged 421.55 per order."),
        ("42 orders have status CANCELLED.", "42 orders were CANCELLED."),
        ("Account 3 placed 17 orders.", "Account 3 placed 17 orders."),
        ("The largest order quantity was 200.", "Maximum quantity: 200."),
        ("There are 24 clients.", "24 clients in total."),
        ("The total traded value for NVDA was 918,240.50.", "NVDA traded value was 918,240.50."),
        ("Japan clients placed 61 orders.", "Clients from Japan placed 61 orders."),
        ("There are 38 accounts.", "38 accounts exist."),
        ("SELL orders totalled 1,975 shares for TSLA.", "TSLA SELL quantity was 1,975."),
        ("The average order quantity was 54.2.", "Average quantity: 54.2."),
        ("12 distinct symbols appear in orders.", "12 distinct symbols were traded."),
        ("Account 7 placed the most orders, with 29.", "Account 7 placed the most orders: 29."),
        ("PENDING orders numbered 35.", "35 orders are PENDING."),
        ("The total BUY traded value was 2,410,300.75.", "BUY value totalled 2,410,300.75."),
    ]
    for g, c in correct_pairs:
        add(g, c, "correct")

    # --- straightforward incorrect answers (judge agrees) ---
    incorrect_pairs = [
        ("360 orders were placed in total.", "There were 320 orders in total."),
        ("The total quantity traded for AAPL was 4,250.", "AAPL total quantity: 3,900."),
        ("There were 185 BUY orders.", "210 BUY orders were placed."),
        ("The average price for MSFT was 421.55.", "MSFT averaged 398.10 per order."),
        ("42 orders have status CANCELLED.", "18 orders were CANCELLED."),
        ("Account 3 placed 17 orders.", "Account 3 placed 22 orders."),
        ("The largest order quantity was 200.", "Maximum quantity: 500."),
        ("There are 24 clients.", "31 clients in total."),
        ("The total traded value for NVDA was 918,240.50.", "NVDA traded value was 750,000.00."),
        ("Japan clients placed 61 orders.", "Clients from Japan placed 44 orders."),
        ("There are 38 accounts.", "41 accounts exist."),
        ("SELL orders totalled 1,975 shares for TSLA.", "TSLA SELL quantity was 2,400."),
        ("The average order quantity was 54.2.", "Average quantity: 61.8."),
        ("12 distinct symbols appear in orders.", "9 distinct symbols were traded."),
        ("Account 7 placed the most orders, with 29.", "Account 7 placed the most orders: 24."),
        ("PENDING orders numbered 35.", "52 orders are PENDING."),
        ("The total BUY traded value was 2,410,300.75.", "BUY value totalled 1,900,000.00."),
    ]
    for g, c in incorrect_pairs:
        add(g, c, "incorrect")

    # --- judge false positives: gold number present, answer still wrong ---
    fp_pairs = [
        ("The total quantity traded for NVDA was 12,400.",
         "The total quantity traded for AAPL was 12,400."),  # wrong symbol
        ("There were 185 BUY orders.",
         "There were 185 SELL orders and 90 BUY orders."),  # wrong side
        ("Account 3 placed 17 orders.",
         "Account 17 placed 3 orders, the busiest of any account."),  # swapped figures, gold num present as account id text? numbers: 17 present
        ("Japan clients placed 61 orders.",
         "Canada clients placed 61 orders."),  # wrong country
        ("The average price for MSFT was 421.55.",
         "The average quantity for MSFT was 421.55 shares."),  # wrong metric
    ]
    for g, c in fp_pairs:
        add(g, c, "incorrect")

    # --- judge false negatives: answer correct, number not verbatim ---
    fn_pairs = [
        ("360 orders were placed in total.",
         "Three hundred sixty orders were placed in total."),  # words, no digits
        ("The total traded value was 1,234,500.",
         "The total traded value was about 1.23 million."),  # rounded
        ("The average order quantity was 54.20.",
         "The average order quantity was roughly fifty-four."),  # words
        ("There were 200 shares in the largest order.",
         "The largest order was for two hundred shares."),  # words
        ("Account 5 placed 20 orders.",
         "Account 5 placed twenty orders."),  # words
    ]
    for g, c in fn_pairs:
        add(g, c, "correct")

    # --- text answers: gold answer with no digits at all ---
    # The judge matches numbers only, so it says "incorrect" to all
    # four; the two correct ones are false negatives by construction,
    # the two incorrect ones true negatives. That is the point: the
    # answer-type split measures a structural blind spot, not a
    # borderline call.
    text_pairs = [
        ("The symbol with the highest traded value was NVDA.",
         "NVDA had the highest traded value.", "correct"),
        ("The symbol with the most orders was AAPL.",
         "AAPL placed the most orders.", "correct"),
        ("The most common order status was FILLED.",
         "Most orders were CANCELLED.", "incorrect"),
        ("The client with the most orders was based in Japan.",
         "The busiest client was based in Canada.", "incorrect"),
    ]
    for g, c, human in text_pairs:
        add(g, c, human)

    return labels


def main():
    out = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "data", "human_labels.jsonl"))
    labels = build_human_labels()
    with open(out, "w") as f:
        for item in labels:
            f.write(json.dumps(item) + "\n")
    result = calibrate(labels)
    print(f"wrote {len(labels)} human labels to {out}")
    print(f"agreement={result['agreement']:.3f} kappa={result['cohens_kappa']:.3f} "
          f"precision={result['precision_correct']:.3f} recall={result['recall_correct']:.3f}")
    print("confusion:", result["confusion"])


if __name__ == "__main__":
    main()
