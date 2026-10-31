"""Deterministic brokerage database (SQLite, seeded).

Schema models a small brokerage: clients in several countries hold
accounts; accounts place orders in securities and hold positions.
The generator is fully seeded so ground truth is reproducible.
"""
import random
import sqlite3

SEED = 42

COUNTRIES = ["United States", "Japan", "United Kingdom", "Canada", "Brazil", "Germany"]
SEGMENTS = ["retail", "advisor", "institutional"]
ACCOUNT_TYPES = ["cash", "margin", "ira"]
CURRENCIES = ["USD", "USD", "USD", "JPY", "GBP"]

SECURITIES = [
    ("AAPL", "Apple Inc", "equity", "technology"),
    ("MSFT", "Microsoft Corp", "equity", "technology"),
    ("NVDA", "NVIDIA Corp", "equity", "technology"),
    ("TSLA", "Tesla Inc", "equity", "consumer"),
    ("AMZN", "Amazon.com Inc", "equity", "consumer"),
    ("GOOGL", "Alphabet Inc", "equity", "technology"),
    ("META", "Meta Platforms Inc", "equity", "technology"),
    ("JPM", "JPMorgan Chase & Co", "equity", "financials"),
    ("V", "Visa Inc", "equity", "financials"),
    ("SPY", "SPDR S&P 500 ETF", "etf", " diversified".strip()),
    ("QQQ", "Invesco QQQ Trust", "etf", "technology"),
    ("BTC/USD", "Bitcoin / US Dollar", "crypto", "crypto"),
]
SYMBOLS = [s[0] for s in SECURITIES]

FIRST = ["Haruka", "Kenji", "Aiko", "Liam", "Emma", "Noah", "Sofia", "Lucas",
         "Mia", "Ethan", "Yuki", "Oliver", "Amelia", "James", "Ren", "Zoe"]
LAST = ["Tanaka", "Smith", "Sato", "Johnson", "Brown", "Suzuki", "Garcia",
        "Miller", "Takahashi", "Wilson", "Moore", "Taylor"]

SCHEMA = """
CREATE TABLE clients (
    client_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    segment TEXT NOT NULL
);
CREATE TABLE accounts (
    account_id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(client_id),
    account_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    opened_year INTEGER NOT NULL
);
CREATE TABLE securities (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    sector TEXT NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    symbol TEXT NOT NULL REFERENCES securities(symbol),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('FILLED', 'CANCELLED', 'PENDING')),
    order_date TEXT NOT NULL
);
CREATE TABLE positions (
    position_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    symbol TEXT NOT NULL REFERENCES securities(symbol),
    quantity INTEGER NOT NULL,
    avg_cost REAL NOT NULL
);
"""

BASE_PRICES = {
    "AAPL": 227.5, "MSFT": 428.1, "NVDA": 131.3, "TSLA": 248.9, "AMZN": 186.4,
    "GOOGL": 171.2, "META": 585.0, "JPM": 218.7, "V": 276.3, "SPY": 572.1,
    "QQQ": 486.5, "BTC/USD": 67240.0,
}


def build_db(path=":memory:", seed=SEED, n_clients=24, n_orders=360):
    """Create and populate the brokerage DB. Returns an open connection."""
    rng = random.Random(seed)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    for cid in range(1, n_clients + 1):
        conn.execute(
            "INSERT INTO clients VALUES (?, ?, ?, ?)",
            (cid, f"{rng.choice(FIRST)} {rng.choice(LAST)}",
             rng.choice(COUNTRIES), rng.choice(SEGMENTS)),
        )
    n_accounts = 0
    for cid in range(1, n_clients + 1):
        for _ in range(rng.choice([1, 1, 2])):
            n_accounts += 1
            conn.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                (n_accounts, cid, rng.choice(ACCOUNT_TYPES),
                 rng.choice(CURRENCIES), rng.randint(2018, 2025)),
            )
    conn.executemany("INSERT INTO securities VALUES (?, ?, ?, ?)", SECURITIES)

    for oid in range(1, n_orders + 1):
        symbol = rng.choice(SYMBOLS)
        price = round(BASE_PRICES[symbol] * rng.uniform(0.9, 1.1), 2)
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (oid, rng.randint(1, n_accounts), symbol,
             rng.choice(["BUY", "SELL"]), rng.choice([1, 5, 10, 25, 50, 100, 200]),
             price, rng.choices(["FILLED", "CANCELLED", "PENDING"], weights=[8, 1, 1])[0],
             f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"),
        )
    pid = 0
    for acct in range(1, n_accounts + 1):
        for symbol in rng.sample(SYMBOLS, rng.randint(1, 4)):
            pid += 1
            conn.execute(
                "INSERT INTO positions VALUES (?, ?, ?, ?, ?)",
                (pid, acct, symbol, rng.choice([10, 25, 50, 100]),
                 round(BASE_PRICES[symbol] * rng.uniform(0.85, 1.05), 2)),
            )
    conn.commit()
    return conn


if __name__ == "__main__":
    c = build_db()
    for t in ("clients", "accounts", "securities", "orders", "positions"):
        print(t, c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
