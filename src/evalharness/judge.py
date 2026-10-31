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
import re


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


def calibrate(labels):
    """labels: list of dicts with gold_answer, candidate_answer, human_label."""
    pairs, rows = [], []
    tp = fp = fn = tn = 0
    for item in labels:
        verdict = judge(item["gold_answer"], item["candidate_answer"])
        human = item["human_label"]
        pairs.append((human, verdict))
        agree = verdict == human
        if human == "correct" and verdict == "correct":
            tp += 1
        elif human == "incorrect" and verdict == "correct":
            fp += 1
        elif human == "correct" and verdict == "incorrect":
            fn += 1
        else:
            tn += 1
        rows.append({**item, "judge_label": verdict, "agree": agree})
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "n": len(labels),
        "agreement": sum(1 for h, j in pairs if h == j) / len(pairs) if pairs else 0.0,
        "cohens_kappa": cohens_kappa(pairs),
        "precision_correct": precision,
        "recall_correct": recall,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "disagreements": [r for r in rows if not r["agree"]],
    }


def build_human_labels():
    """44 human-labelled examples: 34 the naive judge gets right,
    10 designed disagreement cases (5 false positives, 5 false negatives)."""
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
