"""SQLite schema + deterministic demo-data seeding.

The schema is a small retail star model (the five data areas RetailMind named:
Sales, Inventory, Product Master, Branch Master, Shrinkage). Data is seeded
relative to "today" so that relative ranges like "yesterday" and "this week"
always have rows to return when someone runs the demo.
"""
from __future__ import annotations
import sqlite3
import datetime as dt
import random
from typing import Optional

from .config import DB_PATH

SCHEMA = """
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS shrinkage_events;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS branches;

CREATE TABLE branches (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE products (
    id              INTEGER PRIMARY KEY,
    sku             TEXT NOT NULL,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    unit_price      REAL NOT NULL,
    reorder_level   INTEGER NOT NULL,   -- at/below this on_hand => needs reorder
    overstock_level INTEGER NOT NULL    -- above this on_hand => overstocked
);

CREATE TABLE sales (
    id         INTEGER PRIMARY KEY,
    branch_id  INTEGER NOT NULL REFERENCES branches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER NOT NULL,
    amount     REAL NOT NULL,
    sale_date  TEXT NOT NULL            -- ISO YYYY-MM-DD
);

CREATE TABLE inventory (
    branch_id  INTEGER NOT NULL REFERENCES branches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    on_hand    INTEGER NOT NULL,
    PRIMARY KEY (branch_id, product_id)
);

CREATE TABLE shrinkage_events (
    id         INTEGER PRIMARY KEY,
    branch_id  INTEGER NOT NULL REFERENCES branches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    event_date TEXT NOT NULL            -- ISO YYYY-MM-DD
);

CREATE INDEX idx_sales_date ON sales(sale_date);
CREATE INDEX idx_shrink_date ON shrinkage_events(event_date);
"""

BRANCHES = [
    (1, "North", "Metro"),
    (2, "South", "Metro"),
    (3, "East", "Coast"),
    (4, "West", "Coast"),
    (5, "Central", "Downtown"),
]

PRODUCTS = [
    # id, sku, name, category, unit_price, reorder_level, overstock_level
    (1,  "BEV-001", "Cola 330ml",        "Beverages", 1.20, 40, 300),
    (2,  "BEV-002", "Spring Water 1L",   "Beverages", 0.90, 50, 400),
    (3,  "SNK-001", "Potato Chips",      "Snacks",    2.10, 30, 250),
    (4,  "SNK-002", "Chocolate Bar",     "Snacks",    1.50, 35, 250),
    (5,  "DAI-001", "Whole Milk 1L",     "Dairy",     1.10, 25, 150),
    (6,  "DAI-002", "Greek Yogurt",      "Dairy",     1.80, 20, 120),
    (7,  "PRO-001", "Bananas (kg)",      "Produce",   0.70, 30, 180),
    (8,  "PRO-002", "Apples (kg)",       "Produce",   1.30, 30, 180),
    (9,  "HOU-001", "Dish Soap",         "Household", 2.50, 15, 100),
    (10, "HOU-002", "Paper Towels",      "Household", 3.20, 15, 100),
    (11, "BEV-003", "Orange Juice 1L",   "Beverages", 2.40, 20, 140),
    (12, "SNK-003", "Mixed Nuts",        "Snacks",    4.10, 15, 90),
]

SHRINK_REASONS = ["theft", "damage", "spoilage", "miscount", "expiry"]


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def build_database(path: Optional[str] = None, today: Optional[dt.date] = None,
                   days: int = 60) -> str:
    """(Re)create and seed the database. Returns the path used.

    Seeding is deterministic (fixed RNG seed) but anchored to `today`, so the
    relative-date KPIs always have current data.
    """
    path = path or DB_PATH
    today = today or dt.date.today()
    rng = random.Random(42)

    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO branches VALUES (?,?,?)", BRANCHES)
        conn.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)", PRODUCTS
        )

        # Sales: for each day in the window, each branch sells a random subset.
        sale_rows = []
        sid = 1
        for d in range(days, -1, -1):
            day = (today - dt.timedelta(days=d)).isoformat()
            for (bid, _bname, _region) in BRANCHES:
                for (pid, _sku, _name, _cat, price, _ro, _os) in PRODUCTS:
                    if rng.random() < 0.55:  # not every product sells every day
                        continue
                    qty = rng.randint(1, 25)
                    amount = round(qty * price, 2)
                    sale_rows.append((sid, bid, pid, qty, amount, day))
                    sid += 1
        conn.executemany(
            "INSERT INTO sales VALUES (?,?,?,?,?,?)", sale_rows
        )

        # Inventory: random on_hand, with a few deliberate stockouts/overstocks
        inv_rows = []
        for (bid, *_b) in BRANCHES:
            for (pid, _sku, _name, _cat, _price, reorder, overstock) in PRODUCTS:
                roll = rng.random()
                if roll < 0.10:
                    on_hand = 0                                  # out of stock
                elif roll < 0.20:
                    on_hand = overstock + rng.randint(10, 120)    # overstocked
                elif roll < 0.35:
                    on_hand = rng.randint(1, reorder)             # low / reorder
                else:
                    on_hand = rng.randint(reorder + 5, overstock) # healthy
                inv_rows.append((bid, pid, on_hand))
        conn.executemany(
            "INSERT INTO inventory VALUES (?,?,?)", inv_rows
        )

        # Shrinkage events scattered across the window
        shrink_rows = []
        eid = 1
        for d in range(days, -1, -1):
            day = (today - dt.timedelta(days=d)).isoformat()
            for (bid, *_b) in BRANCHES:
                if rng.random() < 0.4:
                    continue
                pid = rng.choice(PRODUCTS)[0]
                qty = rng.randint(1, 6)
                reason = rng.choice(SHRINK_REASONS)
                shrink_rows.append((eid, bid, pid, qty, reason, day))
                eid += 1
        conn.executemany(
            "INSERT INTO shrinkage_events VALUES (?,?,?,?,?,?)", shrink_rows
        )

        conn.commit()
    finally:
        conn.close()
    return path
