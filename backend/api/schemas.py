"""
backend/api/schemas.py
======================
Response shapes shared between the API and the frontend.

Most endpoints return plain dicts straight from the engines, because those
structures are already the contract and wrapping them in a second set of
models would mean updating two files every time a check is added. This file
holds the shapes that genuinely need to be fixed and documented.

CONVENTIONS
  * snake_case everywhere.
  * Percentages travel as FRACTIONS. 0.2711 means 27.11%. Format at the edge.
  * Money is INR crore as a plain number. No currency symbols in JSON.
  * A value that could not be computed is null, never 0 and never "N/A".
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

Status = Literal["PASS", "WARN", "FAIL", "INFO"]


class ErrorResponse(BaseModel):
    """
    Every failure comes back in this shape so the UI has one error path.
    `detail` is written to be shown to a user as-is — no stack traces.
    """
    error: str
    detail: str
    hint: Optional[str] = None


class Finding(BaseModel):
    """One check performed by the review engine."""
    check_id: str
    category: str
    statement: str
    period: str
    rule: str
    expected: Optional[float]
    found: Optional[float]
    delta: Optional[float]
    status: Status
    root_cause: bool
    note: str


class NarrativeSection(BaseModel):
    """
    One block of commentary.

    `source` says whether the words came from the model or our own template.
    `number_check` is FLAGGED when the model cited a figure we never supplied.
    """
    section_code: str
    heading: str
    commentary: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    source: str
    number_check: Literal["PASS", "FLAGGED"]
    unverified_numbers: List[str]
