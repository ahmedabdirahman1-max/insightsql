"""Orchestration: question -> intent -> deterministic SQL -> rows -> explanation.

Returns a transparent result envelope: the business answer, plus the exact SQL
that ran, the bound parameters, and the assumptions made (date interpretation,
branch filter, currency). Surfacing all three is what turns a black-box number
into an auditable one.
"""
from __future__ import annotations
import sqlite3
from typing import Any, Dict, List

from .dates import resolve_range
from .intent import parse_intent
from .kpis import KPIS

SAMPLE_QUESTIONS = [
    "What were sales yesterday?",
    "Which branch had the highest sales this week?",
    "Which branch had the highest shrinkage this month?",
    "Which products are out of stock?",
    "Which products are overstocked at North?",
    "Top 5 products last 30 days",
    "What products are running low and need reorder?",
]


def _inline_sql(sql: str, params: List[Any]) -> str:
    """Render a display-only SQL string with params substituted in.

    Used purely for showing the user what ran — execution always uses the
    parameterised form, so this is never an injection path.
    """
    out = sql
    for val in params:
        literal = f"'{val}'" if isinstance(val, str) else str(val)
        out = out.replace("?", literal, 1)
    return out


def answer_question(question: str, conn: sqlite3.Connection) -> Dict[str, Any]:
    intent = parse_intent(question)
    kpi = intent.get("kpi")

    if not kpi:
        return {
            "question": question,
            "kpi": None,
            "mode": intent.get("mode", "rules"),
            "answer": ("I couldn't map that to a supported metric. Try asking about "
                       "sales, top products, shrinkage, or stock levels."),
            "assumptions": [],
            "sql": None,
            "columns": [],
            "rows": [],
        }

    meta = KPIS[kpi]
    params: Dict[str, Any] = {"limit": intent.get("limit", 5)}
    assumptions: List[str] = []

    if meta["needs_date"]:
        start, end, human = resolve_range(intent.get("date_range", "last_30_days"))
        params["date_start"], params["date_end"] = start, end
        assumptions.append(human)

    branch = intent.get("branch")
    if branch:
        row = conn.execute("SELECT id FROM branches WHERE name = ?", (branch,)).fetchone()
        if row:
            params["branch_id"] = row["id"]
            params["branch_name"] = branch
            assumptions.append(f"Filtered to the {branch} branch.")

    sql, sql_params, _kind = meta["build"](params)
    cur = conn.execute(sql, sql_params)
    columns = [d[0] for d in cur.description]
    rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    answer = meta["explain"](rows, params)
    assumptions.append("Monetary values are in USD.")

    return {
        "question": question,
        "kpi": kpi,
        "mode": intent.get("mode", "rules"),
        "answer": answer,
        "assumptions": assumptions,
        "sql": _inline_sql(sql, sql_params),
        "columns": columns,
        "rows": rows,
    }
