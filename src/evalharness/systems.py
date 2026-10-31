"""Candidate text-to-SQL systems.

Both systems are rule-based translators over the gold question templates.
That is deliberate (see README): it makes the A/B experiment reproducible
offline, and isolates the evaluation methodology from model access.
Replace `system_b`'s body with an LLM call and the harness is unchanged.

system_a — baseline with realistic, documented weaknesses:
  1. Ignores the order-side filter (BUY/SELL) in counts, sums and values.
  2. Computes average *quantity* when asked for average *price*.
  3. Ignores the FILLED status filter in filled-quantity questions.
  4. Ignores the client-country filter (counts all orders instead of
     joining through accounts -> clients).

system_b — improved system that handles every template, including joins,
two-filter questions, and top-N rankings.
"""
import re

COUNTRIES = ["United States", "United Kingdom", "Japan", "Canada", "Brazil", "Germany"]


def _country(q):
    for c in COUNTRIES:
        if c in q:
            return c
    return None


def _symbol(q):
    m = re.search(r"\b(AAPL|MSFT|NVDA|TSLA|AMZN|GOOGL|META|JPM|V|SPY|QQQ|BTC/USD)\b", q)
    return m.group(1) if m else None


def _side(q):
    m = re.search(r"\b(BUY|SELL)\b", q)
    return m.group(1) if m else None


def _translate(question, flawed):
    q = question.strip()

    # --- top-N (check before generic sum questions) ---
    if "highest total quantity traded" in q:
        return ("SELECT symbol FROM orders GROUP BY symbol "
                "ORDER BY SUM(quantity) DESC LIMIT 1")
    if "highest total traded value" in q:
        return ("SELECT symbol FROM orders GROUP BY symbol "
                "ORDER BY SUM(quantity * price) DESC LIMIT 1")
    if "account placed the most orders" in q:
        return ("SELECT account_id FROM orders GROUP BY account_id "
                "ORDER BY COUNT(*) DESC LIMIT 1")

    # --- country questions (join) ---
    country = _country(q)
    if country and "clients" in q:
        if flawed:
            # Weakness 4: no join, no country filter.
            if "total traded value" in q:
                return "SELECT SUM(quantity * price) FROM orders"
            return "SELECT COUNT(*) FROM orders"
        join = ("FROM orders o JOIN accounts a ON o.account_id = a.account_id "
                "JOIN clients cl ON a.client_id = cl.client_id "
                f"WHERE cl.country = '{country}'")
        if "total traded value" in q:
            return f"SELECT SUM(o.quantity * o.price) {join}"
        return f"SELECT COUNT(*) {join}"

    # --- per-account count ---
    m = re.search(r"by account (\d+)", q)
    if m:
        return f"SELECT COUNT(*) FROM orders WHERE account_id = {m.group(1)}"

    # --- distinct / extremes / global averages ---
    if "distinct symbols" in q:
        return "SELECT COUNT(DISTINCT symbol) FROM orders"
    if "distinct accounts" in q:
        return "SELECT COUNT(DISTINCT account_id) FROM orders"
    if "largest order quantity" in q:
        return "SELECT MAX(quantity) FROM orders"
    if "average order quantity across all" in q:
        return "SELECT AVG(quantity) FROM orders"

    sym, side = _symbol(q), _side(q)

    # --- average quantity by side ---
    if "average quantity of" in q and side:
        if flawed:  # side filter ignored (weakness 1 applies to avgs too)
            return "SELECT AVG(quantity) FROM orders"
        return f"SELECT AVG(quantity) FROM orders WHERE side = '{side}'"

    # --- average price by symbol ---
    if "average order price" in q and sym:
        if flawed:  # Weakness 2: averages the wrong column.
            return f"SELECT AVG(quantity) FROM orders WHERE symbol = '{sym}'"
        return f"SELECT AVG(price) FROM orders WHERE symbol = '{sym}'"

    # --- filled-only quantity by symbol ---
    if "FILLED orders for" in q and sym:
        if flawed:  # Weakness 3: status filter dropped.
            return f"SELECT SUM(quantity) FROM orders WHERE symbol = '{sym}'"
        return (f"SELECT SUM(quantity) FROM orders "
                f"WHERE status = 'FILLED' AND symbol = '{sym}'")

    # --- quantity by side + symbol ---
    if "quantity for" in q and side and sym:
        if flawed:
            return f"SELECT SUM(quantity) FROM orders WHERE symbol = '{sym}'"
        return (f"SELECT SUM(quantity) FROM orders "
                f"WHERE side = '{side}' AND symbol = '{sym}'")

    # --- total traded value of all <side> orders ---
    if "total traded value of all" in q and side:
        if flawed:
            return "SELECT SUM(quantity * price) FROM orders"
        return f"SELECT SUM(quantity * price) FROM orders WHERE side = '{side}'"

    # --- total quantity / value by symbol ---
    if "total quantity traded for" in q and sym:
        return f"SELECT SUM(quantity) FROM orders WHERE symbol = '{sym}'"
    if "total traded value for" in q and sym:
        return f"SELECT SUM(quantity * price) FROM orders WHERE symbol = '{sym}'"

    # --- counts by status ---
    m = re.search(r"status (FILLED|CANCELLED|PENDING)", q)
    if m:
        return f"SELECT COUNT(*) FROM orders WHERE status = '{m.group(1)}'"

    # --- counts by side ---
    if re.match(r"How many (BUY|SELL) orders", q) and side:
        if flawed:
            return "SELECT COUNT(*) FROM orders"
        return f"SELECT COUNT(*) FROM orders WHERE side = '{side}'"

    # --- total counts ---
    if "How many orders were placed in total" in q:
        return "SELECT COUNT(*) FROM orders"
    if "How many clients" in q:
        return "SELECT COUNT(*) FROM clients"
    if "How many accounts" in q:
        return "SELECT COUNT(*) FROM accounts"
    if "How many securities" in q:
        return "SELECT COUNT(*) FROM securities"

    return None  # no SQL generated


def system_a(question):
    """Baseline system (flawed — see module docstring)."""
    return _translate(question, flawed=True)


def system_b(question):
    """Improved system handling all gold templates."""
    return _translate(question, flawed=False)


SYSTEMS = {"system_a": system_a, "system_b": system_b}
