"""Accuracy tests for the governed KPI layer.

These exist to make "95%+ accuracy" demonstrable rather than asserted: KPI
results are checked against independent counts on a deterministically-seeded
database, date boundaries are pinned, and intent mapping is verified.

Run from the project root:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import build_database, connect            # noqa: E402
from app.dates import resolve_range                   # noqa: E402
from app.intent import parse_intent_rules             # noqa: E402
from app.service import answer_question, SAMPLE_QUESTIONS  # noqa: E402


class DateTests(unittest.TestCase):
    def test_yesterday_and_today(self):
        today = dt.date(2026, 6, 14)
        s, e, _ = resolve_range("yesterday", today)
        self.assertEqual(s, "2026-06-13")
        self.assertEqual(e, "2026-06-13")
        s, e, _ = resolve_range("today", today)
        self.assertEqual(s, e)
        self.assertEqual(e, "2026-06-14")

    def test_this_week_starts_monday(self):
        today = dt.date(2026, 6, 14)  # a Sunday
        s, e, _ = resolve_range("this_week", today)
        self.assertEqual(s, "2026-06-08")  # Monday
        self.assertEqual(e, "2026-06-14")

    def test_unknown_range_defaults_and_flags(self):
        _, _, human = resolve_range("since forever", dt.date(2026, 6, 14))
        self.assertIn("default", human)


class KpiAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, "test.db")
        build_database(cls.path)  # seeded relative to real today
        cls.conn = connect(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_out_of_stock_matches_independent_count(self):
        res = answer_question("Which products are out of stock?", self.conn)
        direct = self.conn.execute(
            "SELECT COUNT(*) FROM inventory WHERE on_hand <= 0").fetchone()[0]
        self.assertEqual(res["kpi"], "out_of_stock")
        self.assertEqual(len(res["rows"]), direct)

    def test_overstocked_rows_truly_over_limit(self):
        res = answer_question("Which products are overstocked?", self.conn)
        self.assertEqual(res["kpi"], "overstocked")
        for r in res["rows"]:
            self.assertGreater(r["on_hand"], r["overstock_level"])

    def test_sales_total_positive_and_has_sql(self):
        res = answer_question("What were total sales last 30 days?", self.conn)
        self.assertEqual(res["kpi"], "sales_total")
        self.assertGreaterEqual(res["rows"][0]["total_sales"], 0)
        self.assertIn("SELECT", res["sql"])
        self.assertNotIn("?", res["sql"])  # params inlined for display

    def test_sales_by_branch_is_sorted_desc(self):
        res = answer_question("Which branch had the highest sales this month?", self.conn)
        self.assertEqual(res["kpi"], "sales_by_branch")
        totals = [r["total_sales"] for r in res["rows"]]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_branch_filter_applies(self):
        res = answer_question("Which products are out of stock at North?", self.conn)
        for r in res["rows"]:
            self.assertEqual(r["branch"], "North")

    def test_every_sample_question_resolves(self):
        for q in SAMPLE_QUESTIONS:
            res = answer_question(q, self.conn)
            self.assertIsNotNone(res["kpi"], f"unmapped: {q}")
            self.assertTrue(res["answer"])


class IntentTests(unittest.TestCase):
    def test_keyword_mapping(self):
        cases = {
            "What were sales yesterday?": "sales_total",
            "which branch had the highest sales this week": "sales_by_branch",
            "Which branch had the highest shrinkage this month?": "shrinkage_by_branch",
            "which products are out of stock": "out_of_stock",
            "anything overstocked?": "overstocked",
            "what is running low and needs reorder": "low_stock",
            "top 3 products last month": "top_products",
        }
        for q, expected in cases.items():
            self.assertEqual(parse_intent_rules(q)["kpi"], expected, q)

    def test_gibberish_is_unmapped(self):
        self.assertIsNone(parse_intent_rules("tell me a joke about pirates")["kpi"])


if __name__ == "__main__":
    unittest.main()
