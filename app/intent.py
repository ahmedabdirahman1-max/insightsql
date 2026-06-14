"""Natural-language question -> structured intent (KPI + parameters).

Two interchangeable parsers, same output contract:

  * rule-based (default): deterministic keyword matching, no network, no key.
  * LLM (optional): if ANTHROPIC_API_KEY is set, Claude picks the KPI and params.

Critically, in *both* modes the model/rules only ever choose a KPI name and a few
constrained parameters. Neither can emit SQL. An unrecognised question returns
kpi=None so the API can ask the user to rephrase instead of guessing.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, Optional

from .config import ANTHROPIC_API_KEY, INTENT_MODEL
from .db import BRANCHES
from .kpis import KPIS, kpi_catalog_text

BRANCH_NAMES = [b[1] for b in BRANCHES]

_DATE_PATTERNS = [
    (r"\byesterday\b", "yesterday"),
    (r"\btoday\b", "today"),
    (r"\bthis week\b", "this_week"),
    (r"\blast week\b", "last_week"),
    (r"\bthis month\b", "this_month"),
    (r"\blast month\b", "last_month"),
    (r"\blast 7 days\b|\bpast 7 days\b|\bpast week\b", "last_7_days"),
    (r"\blast 30 days\b|\bpast 30 days\b", "last_30_days"),
    (r"\byear to date\b|\bytd\b", "ytd"),
    (r"\ball time\b|\ball-time\b", "all"),
]

# Order matters: more specific KPIs are checked before generic "sales".
_RULE_ORDER = [
    "out_of_stock", "overstocked", "low_stock",
    "shrinkage_by_branch", "top_products", "sales_by_branch", "sales_total",
]


def _detect_date_range(q: str) -> Optional[str]:
    for pattern, name in _DATE_PATTERNS:
        if re.search(pattern, q):
            return name
    return None


def _detect_branch(q: str) -> Optional[str]:
    for name in BRANCH_NAMES:
        if re.search(rf"\b{name.lower()}\b", q):
            return name
    return None


def _detect_limit(q: str, default: int = 5) -> int:
    m = re.search(r"\btop\s+(\d{1,2})\b", q)
    return int(m.group(1)) if m else default


def _detect_kpi_rules(q: str) -> Optional[str]:
    # "top 5 products", "top sellers" etc. — handled before generic keywords
    # because the number breaks a plain substring match on "top products".
    if re.search(r"\btop\b", q) and ("product" in q or "sell" in q or "item" in q):
        return "top_products"
    for kpi in _RULE_ORDER:
        for kw in KPIS[kpi]["keywords"]:
            if kw in q:
                return kpi
    # "which branch" alone implies the per-branch sales ranking
    if "which branch" in q and "shrink" not in q:
        return "sales_by_branch"
    return None


def _assemble(kpi: Optional[str], q: str, mode: str,
              date_range: Optional[str] = None,
              branch: Optional[str] = None,
              limit: Optional[int] = None) -> Dict[str, Any]:
    if kpi not in KPIS:
        return {"kpi": None, "mode": mode}
    out: Dict[str, Any] = {"kpi": kpi, "mode": mode}
    if KPIS[kpi]["needs_date"]:
        out["date_range"] = date_range or _detect_date_range(q) or "last_30_days"
    out["branch"] = branch if branch in BRANCH_NAMES else _detect_branch(q)
    out["limit"] = limit or _detect_limit(q)
    return out


def parse_intent_rules(question: str) -> Dict[str, Any]:
    q = question.lower().strip()
    return _assemble(_detect_kpi_rules(q), q, "rules")


# --------- optional LLM parser ---------

_SYSTEM = (
    "You translate a retail-analytics question into a JSON intent. "
    "You must NOT write SQL. Choose exactly one KPI from the catalog and fill "
    "parameters. Respond with ONLY a JSON object, no prose.\n\n"
    "KPI catalog:\n{catalog}\n\n"
    "JSON shape: {{\"kpi\": <one of the names above or null>, "
    "\"date_range\": <one of: today, yesterday, this_week, last_week, this_month, "
    "last_month, last_7_days, last_30_days, ytd, all, or null>, "
    "\"branch\": <one of {branches} or null>, \"limit\": <int or null>}}. "
    "Use null for anything not specified. If the question doesn't match any KPI, set kpi to null."
)


def parse_intent_llm(question: str) -> Dict[str, Any]:
    """Use Claude to pick the KPI + params. Falls back to rules on any failure."""
    try:
        import anthropic  # imported lazily so the app runs without the package
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        system = _SYSTEM.format(
            catalog=kpi_catalog_text(),
            branches=", ".join(BRANCH_NAMES),
        )
        msg = client.messages.create(
            model=INTENT_MODEL,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        kpi = data.get("kpi")
        if kpi not in KPIS:
            return {"kpi": None, "mode": "llm"}
        return _assemble(
            kpi, question.lower(), "llm",
            date_range=data.get("date_range"),
            branch=data.get("branch"),
            limit=data.get("limit"),
        )
    except Exception:
        # Network/key/parse problems must never break the demo.
        out = parse_intent_rules(question)
        out["mode"] = "rules (llm-fallback)"
        return out


def parse_intent(question: str) -> Dict[str, Any]:
    if ANTHROPIC_API_KEY:
        return parse_intent_llm(question)
    return parse_intent_rules(question)
