"""Gold text-to-SQL dataset generator.

Produces templated questions across >=8 categories with gold SQL whose
execution result on the seeded DB is the ground-truth answer.
Checked-in output: data/gold.jsonl
"""
import json
import os

SIDES = ["BUY", "SELL"]
STATUSES = ["FILLED", "CANCELLED", "PENDING"]
COUNTRIES = ["Japan", "United States", "Canada", "Brazil"]
SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]


def generate_gold():
    items = []

    def add(q, sql, category, difficulty="easy"):
        items.append({"id": f"q{len(items)+1:03d}", "question": q,
                      "gold_sql": sql, "category": category,
                      "difficulty": difficulty})

    # 1. total counts
    add("How many orders were placed in total?",
        "SELECT COUNT(*) FROM orders", "count_total")
    add("How many clients are there in total?",
        "SELECT COUNT(*) FROM clients", "count_total")
    add("How many accounts are there in total?",
        "SELECT COUNT(*) FROM accounts", "count_total")
    add("How many securities are listed in total?",
        "SELECT COUNT(*) FROM securities", "count_total")
    # 2. counts by side
    for s in SIDES:
        add(f"How many {s} orders were placed?",
            f"SELECT COUNT(*) FROM orders WHERE side = '{s}'", "count_by_side")
    # 3. counts by status
    for s in STATUSES:
        add(f"How many orders have status {s}?",
            f"SELECT COUNT(*) FROM orders WHERE status = '{s}'", "count_by_status")
    # 4. counts by country (join clients<-accounts<-orders)
    for c in COUNTRIES:
        add(f"How many orders were placed by clients from {c}?",
            "SELECT COUNT(*) FROM orders o JOIN accounts a ON o.account_id = a.account_id "
            f"JOIN clients cl ON a.client_id = cl.client_id WHERE cl.country = '{c}'",
            "count_by_country", "hard")
    # 5. total quantity by symbol
    for sym in SYMBOLS:
        add(f"What is the total quantity traded for {sym}?",
            f"SELECT SUM(quantity) FROM orders WHERE symbol = '{sym}'",
            "sum_quantity_by_symbol")
    # 6. total traded value by symbol
    for sym in SYMBOLS:
        add(f"What is the total traded value for {sym}?",
            f"SELECT SUM(quantity * price) FROM orders WHERE symbol = '{sym}'",
            "sum_value_by_symbol", "hard")
    # 7. average price by symbol
    for sym in SYMBOLS:
        add(f"What is the average order price for {sym}?",
            f"SELECT AVG(price) FROM orders WHERE symbol = '{sym}'",
            "avg_price_by_symbol")
    # 8. quantity by side AND symbol (two filters)
    for s in SIDES:
        for sym in ["AAPL", "NVDA", "TSLA"]:
            add(f"What is the total {s} quantity for {sym}?",
                f"SELECT SUM(quantity) FROM orders WHERE side = '{s}' AND symbol = '{sym}'",
                "sum_quantity_by_side_symbol", "hard")
    # 9. top-N
    add("Which symbol has the highest total quantity traded?",
        "SELECT symbol FROM orders GROUP BY symbol ORDER BY SUM(quantity) DESC LIMIT 1",
        "top_symbol_by_volume", "hard")
    add("Which symbol has the highest total traded value?",
        "SELECT symbol FROM orders GROUP BY symbol ORDER BY SUM(quantity * price) DESC LIMIT 1",
        "top_symbol_by_value", "hard")
    add("Which account placed the most orders?",
        "SELECT account_id FROM orders GROUP BY account_id ORDER BY COUNT(*) DESC LIMIT 1",
        "top_account_by_orders", "hard")
    # 10. per-account counts
    for acct in [1, 2, 3, 5, 8]:
        add(f"How many orders were placed by account {acct}?",
            f"SELECT COUNT(*) FROM orders WHERE account_id = {acct}",
            "count_by_account")
    # 11. value by side
    for s in SIDES:
        add(f"What is the total traded value of all {s} orders?",
            f"SELECT SUM(quantity * price) FROM orders WHERE side = '{s}'",
            "sum_value_by_side")
    # 12. distinct / misc aggregates
    add("How many distinct symbols appear in orders?",
        "SELECT COUNT(DISTINCT symbol) FROM orders", "distinct_count")
    add("How many distinct accounts placed orders?",
        "SELECT COUNT(DISTINCT account_id) FROM orders", "distinct_count")
    add("What is the largest order quantity placed?",
        "SELECT MAX(quantity) FROM orders", "max_quantity")
    add("What is the average order quantity across all orders?",
        "SELECT AVG(quantity) FROM orders", "avg_quantity")
    for s in SIDES:
        add(f"What is the average quantity of {s} orders?",
            f"SELECT AVG(quantity) FROM orders WHERE side = '{s}'",
            "avg_quantity_by_side")
    # 13. total value by country
    for c in ["Japan", "United States"]:
        add(f"What is the total traded value from clients in {c}?",
            "SELECT SUM(o.quantity * o.price) FROM orders o "
            "JOIN accounts a ON o.account_id = a.account_id "
            f"JOIN clients cl ON a.client_id = cl.client_id WHERE cl.country = '{c}'",
            "sum_value_by_country", "hard")
    # 14. filled-only quantity by symbol (status + symbol)
    for sym in ["AAPL", "MSFT", "NVDA"]:
        add(f"What is the total quantity of FILLED orders for {sym}?",
            f"SELECT SUM(quantity) FROM orders WHERE status = 'FILLED' AND symbol = '{sym}'",
            "sum_quantity_filled_by_symbol", "hard")
    return items


def main(out=None):
    out = out or os.path.join(os.path.dirname(__file__), "..", "..", "data", "gold.jsonl")
    out = os.path.normpath(out)
    items = generate_gold()
    with open(out, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    cats = sorted({i["category"] for i in items})
    print(f"wrote {len(items)} gold items across {len(cats)} categories to {out}")
    print("categories:", ", ".join(cats))


if __name__ == "__main__":
    main()
