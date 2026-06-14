"""FastAPI entrypoint.

Run:  uvicorn app.main:app --reload
Then open http://127.0.0.1:8000

On startup the demo database is created and seeded if it doesn't exist yet.
"""
from __future__ import annotations
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DB_PATH, ANTHROPIC_API_KEY, INTENT_MODEL
from .db import build_database, connect
from .service import answer_question, SAMPLE_QUESTIONS

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="InsightSQL Text-to-SQL (demo)", version="1.0.0")


class AskRequest(BaseModel):
    question: str


@app.on_event("startup")
def _ensure_db() -> None:
    if not os.path.exists(DB_PATH):
        build_database(DB_PATH)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "intent_parser": "llm" if ANTHROPIC_API_KEY else "rules",
        "intent_model": INTENT_MODEL if ANTHROPIC_API_KEY else None,
    }


@app.get("/api/samples")
def samples() -> dict:
    return {"samples": SAMPLE_QUESTIONS}


@app.post("/api/ask")
def ask(req: AskRequest) -> JSONResponse:
    question = (req.question or "").strip()
    if not question:
        return JSONResponse({"error": "Empty question."}, status_code=400)
    conn = connect(DB_PATH)
    try:
        result = answer_question(question, conn)
    finally:
        conn.close()
    return JSONResponse(result)


# Serve static assets (index.html is returned by "/" above).
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
