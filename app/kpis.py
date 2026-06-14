"""The governed KPI / semantic layer — the core of the anti-hallucination design.

The LLM never writes SQL. It only chooses one KPI from this registry and fills a
small, validated set of parameters. Every query below is a hand-written,
parameterised template, so the SQL that runs is always one a developer reviewed.
This is what makes "95%+ accuracy" a property of the system rather than a hope
about the model.

Each KPI declares:
  description : human summary (also shown to the LLM so it can pick correctly)
  keywords    : used by the no-API rule-based parser
  needs_date  : whether a date range applies
  build(p)    : returns (sql, params, kind) from already-resolved params
  explain(...): turns result rows into a plain-English business answer
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Tuple

Rows = List[Dict[str, Any]]


def _branch_clause(p: Dict[str, Any], col: str) -> Tuple[str, list]:
    """Optional branch filter shared by several KPIs."""
    if p.get("branch_id"):
        return f" AND {col} = ?", [p["branch_id"]]
    return "", []


# ---------- build functions ----------

def _build_sales_total(p):
    clause, bparams = _branch_clause(p, "branch_id")
    sql = (
        "SELECT COALESCE(SUM(amount),0) AS total_sales, "
        "COALESCE(SUM(qty),0) AS units_sold "
        "FROM sales WHERE sale_date BETWEEN ? AND ?" + clause
    )
    return sql, [p["date_start"], p["date_end"], *bparams], "scalar"


def _build_sales_by_branch(p):
    sql = (
        "SELECT b.name AS branch, COALESCE(SUM(s.amount),0) AS total_sales "
        "FROM branches b "
        "LEFT JOIN sales s ON s.branch_id = b.id AND s.sale_date BETWEEN ? AND ? "
        "GROUP BY b.id ORDER BY total_sales DESC"
    )
    return sql, [p["date_start"], p["date_end"]], "table"


def _build_shrinkage_by_branch(p):
    sql = (
        "SELECT b.name AS branch, COALESCE(SUM(se.qty),0) AS units_lost, "
        "ROUND(COALESCE(SUM(se.qty * p.unit_price),0),2) AS shrinkage_value "
        "FROM branches b "
        "LEFT JOIN shrinkage_events se ON se.branch_id = b.id "
        "AND se.event_date BETWEEN ? AND ? "
        "LEFT JOIN products p ON p.id = se.product_id "
        "GROUP BY b.id ORDER BY shrinkage_value DESC"
    )
    return sql, [p["date_start"], p["date_end"]], "table"


def _build_out_of_stock(p):
    clause, bparams = _branch_clause(p, "b.id")
    sql = (
        "SELECT b.name AS branch, pr.sku, pr.name AS product "
        "FROM inventory i "
        "JOIN products pr ON pr.id = i.product_id "
        "JOIN branches b ON b.id = i.branch_id "
        "WHERE i.on_hand <= 0" + clause +
        " ORDER BY b.name, pr.name"
    )
    return sql, [*bparams], "table"


def _build_overstocked(p):
    clause, bparams = _branch_clause(p, "b.id")
    sql = (
        "SELECT b.name AS branch, pr.sku, pr.name AS product, "
        "i.on_hand, pr.overstock_level, (i.on_hand - pr.overstock_level) AS excess_units "
        "FROM inventory i "
        "JOIN products pr ON pr.id = i.product_id "
        "JOIN branches b ON b.id = i.branch_id "
        "WHERE i.on_hand > pr.overstock_level" + clause +
        " ORDER BY excess_units DESC"
    )
    return sql, [*bparams], "table"


def _build_low_stock(p):
    clause, bparams = _branch_clause(p, "b.id")
    sql = (
        "SELECT b.name AS branch, pr.sku, pr.name AS product, "
        "i.on_hand, pr.reorder_level "
        "FROM inventory i "
        "JOIN products pr ON pr.id = i.product_id "
        "JOIN branches b ON b.id = i.branch_id "
        "WHERE i.on_hand > 0 AND i.on_hand <= pr.reorder_level" + clause +
        " ORDER BY (pr.reorder_level - i.on_hand) DESC"
    )
    return sql, [*bparams], "table"


def _build_top_products(p):
    clause, bparams = _branch_clause(p, "s.branch_id")
    sql = (
        "SELECT pr.name AS product, SUM(s.qty) AS units_sold, "
        "ROUND(SUM(s.amount),2) AS total_sales "
        "FROM sales s JOIN products pr ON pr.id = s.product_id "
        "WHERE s.sale_date BETWEEN ? AND ?" + clause +
        " GROUP BY pr.id ORDER BY total_sales DESC LIMIT ?"
    )
    return sql, [p["date_start"], p["date_end"], *bparams, p.get("limit", 5)], "table"


# ---------- explain functions ----------

def _money(x) -> str:
    return "${:,.2f}".format(x or 0)


def _explain_sales_total(rows: Rows, p) -> str:
    r = rows[0] if rows else {"total_sales": 0, "units_sold": 0}
    where = f" at the {p['branch_name']} branch" if p.get("branch_name") else ""
    return (f"Total sales{where} were {_money(r['total_sales'])} "
            f"across {int(r['units_sold'] or 0):,} units.")


def _explain_sales_by_branch(rows: Rows, p) -> str:
    if not rows:
        return "No sales found for that period."
    top = rows[0]
    return (f"{top['branch']} led with {_money(top['total_sales'])}. "
            f"Ranked across {len(rows)} branches.")


def _explain_shrinkage(rows: Rows, p) -> str:
    ranked = [r for r in rows if (r.get("shrinkage_value") or 0) > 0]
    if not ranked:
        return "No shrinkage recorded for that period."
    top = ranked[0]
    return (f"{top['branch']} had the highest shrinkage: {_money(top['shrinkage_value'])} "
            f"({int(top['units_lost'])} units lost).")


def _explain_out_of_stock(rows: Rows, p) -> str:
    if not rows:
        return "No products are currently out of stock."
    where = f" at {p['branch_name']}" if p.get("branch_name") else ""
    return f"{len(rows)} product-locations are out of stock{where}."


def _explain_overstocked(rows: Rows, p) -> str:
    if not rows:
        return "No products are currently overstocked."
    return (f"{len(rows)} product-locations are overstocked. "
            f"Worst: {rows[0]['product']} at {rows[0]['branch']} "
            f"({int(rows[0]['excess_units'])} units over limit).")


def _explain_low_stock(rows: Rows, p) -> str:
    if not rows:
        return "No products are below their reorder level."
    return f"{len(rows)} product-locations are at or below reorder level."


def _explain_top_products(rows: Rows, p) -> str:
    if not rows:
        return "No sales found for that period."
    return (f"Top seller was {rows[0]['product']} at {_money(rows[0]['total_sales'])}. "
            f"Showing top {len(rows)}.")


# ---------- registry ----------

KPIS: Dict[str, Dict[str, Any]] = {
    "sales_total": {
        "description": "Total sales amount and units for a period, optionally for one branch.",
        "keywords": ["sales", "revenue", "how much did we sell", "total sales"],
        "needs_date": True,
        "build": _build_sales_total,
        "explain": _explain_sales_total,
    },
    "sales_by_branch": {
        "description": "Sales totals per branch for a period; identifies the highest/lowest branch.",
        "keywords": ["which branch", "branch had the highest sales", "sales by branch", "best branch"],
        "needs_date": True,
        "build": _build_sales_by_branch,
        "explain": _explain_sales_by_branch,
    },
    "shrinkage_by_branch": {
        "description": "Shrinkage (loss) units and value per branch for a period; finds worst branch.",
        "keywords": ["shrinkage", "loss", "theft", "shrink"],
        "needs_date": True,
        "build": _build_shrinkage_by_branch,
        "explain": _explain_shrinkage,
    },
    "out_of_stock": {
        "description": "Products with zero on-hand stock, optionally for one branch.",
        "keywords": ["out of stock", "stockout", "stock out", "zero stock", "unavailable"],
        "needs_date": False,
        "build": _build_out_of_stock,
        "explain": _explain_out_of_stock,
    },
    "overstocked": {
        "description": "Products whose on-hand exceeds their overstock level.",
        "keywords": ["overstock", "overstocked", "too much stock", "excess stock"],
        "needs_date": False,
        "build": _build_overstocked,
        "explain": _explain_overstocked,
    },
    "low_stock": {
        "description": "Products at or below reorder level (but not yet zero) — need reordering.",
        "keywords": ["low stock", "reorder", "running low", "need to restock"],
        "needs_date": False,
        "build": _build_low_stock,
        "explain": _explain_low_stock,
    },
    "top_products": {
        "description": "Best-selling products by revenue for a period, optionally for one branch.",
        "keywords": ["top products", "best selling", "best-selling", "top sellers", "most sold"],
        "needs_date": True,
        "build": _build_top_products,
        "explain": _explain_top_products,
    },
}


def kpi_catalog_text() -> str:
    """Compact catalog string handed to the LLM so it can pick a KPI by name."""
    return "\n".join(f"- {name}: {meta['description']}" for name, meta in KPIS.items())
