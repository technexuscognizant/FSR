"""
backend/api/main.py
===================
The FastAPI server. One pipeline: fixed-schema statement review.

Run it:
    uvicorn backend.api.main:app --reload --port 8000

Then open http://localhost:8000/docs for the interactive API browser FastAPI
generates from the type hints — the frontend team can click every endpoint
there before writing a line of UI code.

THE FLOW
    POST /upload             one .xlsx, or several .csv  -> session_id
    POST /review/{sid}       every check, grouped A-E
    POST /narrative/{sid}    AI commentary on those findings
    GET  /compare?a=&b=      benchmark two uploaded companies
    GET  /wp514/{sid}        download the audit workpaper

Nothing here computes anything. Each handler takes a request, calls the
engine that owns the work, and returns the result. Business logic in a route
handler is how a codebase rots.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.api import store
from backend.api.schemas import ErrorResponse
from backend.ingestion.loader import load_statements, supported_formats
from backend.ingestion.statements import StatementError
from backend.review.engine import StatementReviewEngine
from backend.review.narrative import StatementNarrativeAgent
from backend.review.peer import compare_statements
from backend.review.wp514 import StatementWP514Generator

VERSION = "1.0.0"

# Refuse anything larger before reading it into memory. A statement workbook
# is a few hundred KB; 10 MB is generous and still stops an accidental huge
# upload from taking the demo down.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(
    title="Financial Statement Reviewer & Planning Analytics Engine",
    version=VERSION,
    description=(
        "Automated review of financial statements: mathematical accuracy, "
        "internal consistency, prior-year tie-outs, ratio verification, and "
        "spelling and grammar. Every figure is computed in Python. The "
        "language model only writes commentary about pre-verified numbers."
    ),
)

# Streamlit runs on a different port, so the browser treats it as a different
# origin and blocks the calls without this. Wide open is fine for a local
# demo; a real deployment would name the exact origins.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


# ── errors ───────────────────────────────────────────────────────────────────

@app.exception_handler(StatementError)
async def handle_statement_error(_request, exc: StatementError) -> JSONResponse:
    """A bad upload is the user's problem to fix, not a server crash."""
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            error="unreadable_file",
            detail=str(exc),
            hint="Upload a workbook matching the standard statement layout, "
                 "or one CSV per statement.",
        ).model_dump(),
    )


def _require_session(session_id: str) -> Dict[str, Any]:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(
            404, f"Session '{session_id}' not found. It may have expired — "
                 f"upload the file again.")
    return session


# ── system ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "statement-reviewer", "version": VERSION}


@app.get("/formats", tags=["system"])
def formats() -> Dict[str, Any]:
    """What the UI should say it accepts. Never hardcode this in the frontend."""
    return {"readers": supported_formats(),
            "extensions": [".xlsx", ".xlsm", ".csv"]}


# ── upload ───────────────────────────────────────────────────────────────────

@app.post("/upload", tags=["ingestion"], responses={400: {"model": ErrorResponse}})
async def upload(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    """
    Accept one Excel workbook OR several CSV files (one per statement).

    The uploaded files are deleted as soon as they are parsed — we keep the
    numbers, not the upload. Nothing downstream needs the original bytes, and
    not storing user files is one less thing to get wrong.
    """
    temp_paths: List[str] = []
    try:
        for item in files:
            name = os.path.basename(item.filename or "upload")
            extension = os.path.splitext(name)[1].lower()
            contents = await item.read()
            if len(contents) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"'{name}' exceeds the size limit.")
            if not contents:
                raise StatementError(f"'{name}' is empty.")
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as handle:
                handle.write(contents)
                temp_paths.append(handle.name)

        data = load_statements(temp_paths if len(temp_paths) > 1 else temp_paths[0])

        # The reader names the company from the path it was given, which for
        # an upload is a random temp file. Use what the user actually sent.
        original_names = [os.path.basename(f.filename or "upload") for f in files]
        data["source_file"] = ", ".join(original_names)
        if len(original_names) == 1:
            from backend.ingestion.readers.meridian_xlsx import _read_company
            data["company_name"] = _read_company(None, set(), original_names[0])
        else:
            stems = [os.path.splitext(n)[0] for n in original_names]
            prefix = os.path.commonprefix(stems).strip("_- ")
            data["company_name"] = (prefix.replace("_", " ") if len(prefix) >= 4
                                    else "Uploaded Statements")
    finally:
        # Cleanup must never be why a request fails. On Windows a stray open
        # handle raises here even though the parse already succeeded.
        for path in temp_paths:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass

    session_id = store.create(data)
    return {
        "session_id": session_id,
        "company_name": data["company_name"],
        "source_file": data["source_file"],
        "source_format": data["source_format"],
        "years": data["years"],
        "label_issues_found": len(data["label_issues"]),
    }


@app.get("/sessions", tags=["ingestion"])
def list_sessions() -> Dict[str, Any]:
    """Everything currently uploaded — powers the company selector."""
    return {"sessions": store.list_all()}


@app.delete("/sessions/{session_id}", tags=["ingestion"])
def delete_session(session_id: str) -> Dict[str, Any]:
    return {"session_id": session_id, "deleted": store.delete(session_id)}


# ── review ───────────────────────────────────────────────────────────────────

@app.post("/review/{session_id}", tags=["review"],
          responses={404: {"model": ErrorResponse}})
def review(session_id: str) -> Dict[str, Any]:
    """
    Run every consistency check. POST because it starts work, though the
    result is cached so a second call is free.
    """
    _require_session(session_id)
    return store.cached(session_id, "review",
                        lambda d: StatementReviewEngine(d).run())


@app.post("/narrative/{session_id}", tags=["review"],
          responses={404: {"model": ErrorResponse}})
def narrative(session_id: str) -> Dict[str, Any]:
    """
    Commentary on the findings. Only computed numbers reach the model, never
    the spreadsheet. If the model is unavailable this still returns a full
    report using text the engine wrote itself.
    """
    _require_session(session_id)
    report = store.cached(session_id, "review",
                          lambda d: StatementReviewEngine(d).run())
    return store.cached(session_id, "narrative",
                        lambda d: StatementNarrativeAgent().run(report))


# ── peer comparison ──────────────────────────────────────────────────────────

@app.get("/compare", tags=["analytics"],
         responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
def compare(
    a: str = Query(..., description="session_id of the first company"),
    b: str = Query(..., description="session_id of the second company"),
) -> Dict[str, Any]:
    """Benchmark two uploaded companies on their latest year."""
    if a == b:
        raise HTTPException(400, "Pick two different sessions to compare.")
    first = _require_session(a)["data"]
    second = _require_session(b)["data"]
    try:
        return compare_statements(first, second)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── workpaper ────────────────────────────────────────────────────────────────

@app.get("/wp514/{session_id}", tags=["review"],
         responses={404: {"model": ErrorResponse}})
def wp514(session_id: str):
    """Build the WP-514 workpaper and stream it back as an .xlsx download."""
    _require_session(session_id)
    report = store.cached(session_id, "review",
                          lambda d: StatementReviewEngine(d).run())
    commentary = store.cached(session_id, "narrative",
                              lambda d: StatementNarrativeAgent().run(report))

    generator = StatementWP514Generator(report, commentary)
    directory = tempfile.mkdtemp(prefix="wp514_")
    path = generator.save(directory)
    return FileResponse(
        path, filename=os.path.basename(path),
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
    )
