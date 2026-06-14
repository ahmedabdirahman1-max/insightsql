# InsightSQL — Governed Text-to-SQL for Retail Analytics

Ask a retail database questions in plain English and get an answer, the exact SQL
that produced it, and the assumptions behind it.

This is a working reference implementation of a pattern I use for production
Text-to-SQL: **the language model never writes SQL.** It only maps a question to
a pre-defined, reviewed KPI and a small set of validated parameters. That single
design choice is what makes accuracy a property of the system instead of a hope
about the model.

> Built as a focused demo: Python · FastAPI · PostgreSQL-style SQL (SQLite for
> zero-setup) · Claude/OpenAI-optional intent parsing · Docker-ready.

---

## Why this design (the part that matters)

Most "AI analytics" demos let an LLM generate raw SQL from a question. That fails
in the expensive way: not with an error, but with a **confident wrong number** —
a silent mis-join, a double-count across a join fan-out, or "this week" read off
the wrong timezone. A retailer then reorders stock on a figure that was never
right.

InsightSQL removes that failure mode by construction:

1. **A governed KPI layer.** Every metric (`sales_total`, `shrinkage_by_branch`,
   `out_of_stock`, …) is a hand-written, parameterised SQL template in
   [`app/kpis.py`](app/kpis.py). The SQL that runs is always SQL a developer reviewed.
2. **The model only classifies.** Intent parsing ([`app/intent.py`](app/intent.py))
   maps the question to *one KPI name plus parameters* — never to SQL. An
   unrecognised question returns "no match" and asks the user to rephrase, rather
   than guessing.
3. **Dates resolve in code, not the prompt.** "Yesterday" / "this week" become
   deterministic, inclusive date boundaries in [`app/dates.py`](app/dates.py).
4. **Every answer is auditable.** The API returns the business answer *plus* the
   exact SQL and the assumptions made (date interpretation, branch filter,
   currency), so a wrong result is visible, not silent.

The intent parser runs in two interchangeable modes:

- **Rule-based (default):** deterministic, no API key, no network.
- **LLM (optional):** set `ANTHROPIC_API_KEY` and Claude does the classification.
  Same output contract; falls back to rules on any error.

---

## Run it

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python seed.py                       # builds & seeds the demo SQLite database
uvicorn app.main:app --reload        # serves http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000> and ask, or click a sample question.

To use the real LLM intent parser:

```bash
cp .env.example .env                 # add your ANTHROPIC_API_KEY
# (load the env however you prefer, then run uvicorn)
```

## Tests

The KPI results are checked against independent counts on a deterministically
seeded database, date boundaries are pinned, and intent mapping is verified —
so "high accuracy" is demonstrable, not asserted.

```bash
python -m unittest discover -s tests -v
```

---

## Example questions

- *What were sales yesterday?*
- *Which branch had the highest sales this week?*
- *Which branch had the highest shrinkage this month?*
- *Which products are out of stock?*  /  *…overstocked at North?*
- *Top 5 products last 30 days*
- *What products are running low and need reorder?*

## Data model

A small retail star schema covering the five areas the metrics need — Sales,
Inventory, Product Master, Branch Master, Shrinkage — seeded with deterministic
demo data anchored to the current date (so relative-date questions always return
rows). See [`app/db.py`](app/db.py).

## Project layout

```
app/
  config.py    env-driven settings
  dates.py     deterministic relative-date resolution
  db.py        schema + demo-data seeding
  kpis.py      the governed KPI/semantic layer (all SQL lives here)
  intent.py    question -> KPI + params (rule-based or Claude)
  service.py   orchestration + auditable result envelope
  main.py      FastAPI app
static/        single-page UI
tests/         accuracy + intent tests
```

## Porting to PostgreSQL

The query templates use standard SQL. Swapping SQLite for PostgreSQL means
pointing the connection at Postgres and adjusting a couple of functions
(`ROUND`, date handling) — the KPI layer, intent parsing, and API are unchanged.

---

*Demo project. The architecture — governed KPI layer, model-as-classifier,
in-code date logic, auditable output — is the same one I'd bring to a production
build.*
