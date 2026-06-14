"""Relative date resolution.

This is deliberately *not* the LLM's job. Letting a model guess what "this week"
means is a top source of confidently-wrong analytics answers (timezone drift,
off-by-one week boundaries). Here every named range maps to deterministic,
inclusive ISO dates, and the human-readable assumption is returned so the answer
is auditable.
"""
from __future__ import annotations
import datetime as dt
from typing import Optional, Tuple


def _today(today: Optional[dt.date] = None) -> dt.date:
    return today or dt.date.today()


def resolve_range(name: str, today: Optional[dt.date] = None) -> Tuple[str, str, str]:
    """Resolve a named relative range to (start_iso, end_iso, human_assumption).

    Range is inclusive on both ends. Unknown names fall back to the last 30 days
    and say so explicitly in the assumption string.
    """
    t = _today(today)
    key = (name or "").strip().lower().replace(" ", "_")

    if key == "today":
        start = end = t
    elif key == "yesterday":
        start = end = t - dt.timedelta(days=1)
    elif key in ("this_week", "week"):
        start = t - dt.timedelta(days=t.weekday())  # Monday
        end = t
    elif key == "last_week":
        this_monday = t - dt.timedelta(days=t.weekday())
        end = this_monday - dt.timedelta(days=1)     # Sunday
        start = end - dt.timedelta(days=6)            # Monday
    elif key in ("this_month", "month"):
        start = t.replace(day=1)
        end = t
    elif key == "last_month":
        first_of_this = t.replace(day=1)
        end = first_of_this - dt.timedelta(days=1)
        start = end.replace(day=1)
    elif key in ("last_7_days", "last_7", "past_7_days"):
        end = t
        start = t - dt.timedelta(days=6)
    elif key in ("last_30_days", "last_30", "past_30_days"):
        end = t
        start = t - dt.timedelta(days=29)
    elif key == "ytd":
        start = t.replace(month=1, day=1)
        end = t
    elif key in ("all", "all_time"):
        start = dt.date(2000, 1, 1)
        end = t
    else:
        end = t
        start = t - dt.timedelta(days=29)
        key = "last_30_days (default — range not recognized)"

    human = f"Interpreted date range as {key.replace('_', ' ')} = {start.isoformat()} to {end.isoformat()} (inclusive)."
    return start.isoformat(), end.isoformat(), human
