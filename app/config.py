"""Runtime configuration, read from environment with safe defaults."""
from __future__ import annotations
import os

# Where the SQLite demo database lives. SQLite keeps the demo zero-setup;
# the query layer uses standard SQL so the same templates port to PostgreSQL.
DB_PATH = os.environ.get("INSIGHTSQL_DB", "insightsql.db")

# If set, the intent parser calls Claude to map a question -> KPI + params.
# If empty, a deterministic rule-based parser is used instead, so the app
# always runs with no API key and no network.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
INTENT_MODEL = os.environ.get("INTENT_MODEL", "claude-haiku-4-5-20251001").strip()
