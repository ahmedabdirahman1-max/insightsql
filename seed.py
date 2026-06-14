"""Build (or reset) the demo database.

Usage:
    python seed.py
"""
from app.config import DB_PATH
from app.db import build_database

if __name__ == "__main__":
    path = build_database(DB_PATH)
    print(f"Seeded RetailMind demo database at: {path}")
