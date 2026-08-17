"""
backend/ingestion/readers/meridian_xlsx.py
==========================================
Reads the fixed-schema statement workbook — one Excel file, six sheets.

Every sheet has the same shape:

    Particular | FY2024 | FY2025 | FY2026

so reading is: take column A as the row label, take the rest as years. No
merged cells, no spacer rows, no header hunting.

Do not import this directly. Use the front door:

    from backend.ingestion.loader import load_statements
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

import pandas as pd

from backend.ingestion.statements import (
    STATEMENTS,
    StatementError,
    build_statement,
    clean_text,
    to_number,
    validate_shape,
)

SOURCE_FORMAT = "meridian_xlsx"
EXTENSIONS = {".xlsx", ".xlsm"}


def looks_like_workbook(path: str) -> bool:
    """
    Is this file ours to read? The dispatcher asks every reader this before
    handing over a file, so it must be fast and must never raise.
    """
    if os.path.splitext(path)[1].lower() not in EXTENSIONS:
        return False
    try:
        with pd.ExcelFile(path) as workbook:
            names = set(workbook.sheet_names)
    except Exception:
        return False
    return {sheet for sheet, _ in STATEMENTS.values()}.issubset(names)


def _rows_and_years(frame: pd.DataFrame) -> tuple[List[tuple], List[str]]:
    """Split a raw sheet into year column names and (label, values) rows."""
    years = [clean_text(column) for column in frame.columns[1:]
             if clean_text(column).upper().startswith("FY")]
    rows = [(row.iloc[0], [row[year] for year in years])
            for _, row in frame.iterrows()]
    return rows, years


def read(path: str) -> Dict[str, Any]:
    """Read the workbook into the canonical shape."""
    if not os.path.exists(path):
        raise StatementError(f"File not found: {path}")

    try:
        workbook = pd.ExcelFile(path)
    except Exception as exc:
        raise StatementError(f"Could not open '{path}' as Excel: {exc}") from exc

    # A context manager is required, not optional. Without it pandas keeps the
    # file handle open and Windows refuses to delete the upload afterwards.
    with workbook as excel:
        present = set(excel.sheet_names)
        required = {sheet for sheet, _ in STATEMENTS.values()}
        if not required.issubset(present):
            raise StatementError(
                "This workbook is not in the expected format. Missing sheet(s): "
                f"{sorted(required - present)}. Found: {sorted(present)}"
            )

        statements: Dict[str, pd.DataFrame] = {}
        label_issues: List[Dict[str, Any]] = []
        years: List[str] = []

        for key, (sheet_name, expected) in STATEMENTS.items():
            raw = pd.read_excel(excel, sheet_name=sheet_name)
            rows, sheet_years = _rows_and_years(raw)
            if not sheet_years:
                raise StatementError(f"'{sheet_name}' has no FY columns.")
            years = years or sheet_years

            frame, issues = build_statement(rows, sheet_years, expected, sheet_name)
            statements[key] = frame
            label_issues.extend(issues)

        ratios = (pd.read_excel(excel, "Key_Ratios")
                  if "Key_Ratios" in present else pd.DataFrame())
        prior_year = (pd.read_excel(excel, "Prior_Year_Published")
                      if "Prior_Year_Published" in present else pd.DataFrame())
        notes = _read_notes(excel, present)
        company = _read_company(excel, present, path)

    payload = {
        "company_name": company,
        "source_file": os.path.basename(path),
        "source_format": SOURCE_FORMAT,
        "years": years,
        "statements": statements,
        "ratios": _tidy_ratios(ratios, years),
        "prior_year": _tidy_prior_year(prior_year),
        "notes": notes,
        "label_issues": label_issues,
    }
    validate_shape(payload)
    return payload


# ── supporting sheets ────────────────────────────────────────────────────────

def _tidy_ratios(raw: pd.DataFrame, years: List[str]) -> pd.DataFrame:
    """
    Published ratios, keyed by metric name, with the Basis column preserved.

    Basis states the formula in words. Keeping it means the ratio check can
    show a reviewer exactly what we recomputed and why we disagree.
    """
    if raw.empty:
        return raw
    frame = raw.copy()
    frame["Metric"] = frame["Metric"].map(clean_text)
    frame = frame.set_index("Metric")
    for year in years:
        if year in frame.columns:
            frame[year] = frame[year].map(to_number)
    return frame


def _tidy_prior_year(raw: pd.DataFrame) -> pd.DataFrame:
    """Figures as filed in last year's report, keyed by line item."""
    if raw.empty:
        return raw
    frame = raw.copy()
    frame["Particular"] = frame["Particular"].map(clean_text)
    frame = frame.set_index("Particular")
    for column in frame.columns:
        frame[column] = frame[column].map(to_number)
    return frame


def _read_notes(excel: pd.ExcelFile, present: set) -> List[Dict[str, str]]:
    """Narrative disclosures — the input to the grammar check."""
    if "Notes" not in present:
        return []
    raw = pd.read_excel(excel, "Notes")
    return [{"note": clean_text(row.iloc[0]), "text": clean_text(row.iloc[1])}
            for _, row in raw.iterrows() if clean_text(row.iloc[1])]


def _read_company(excel: pd.ExcelFile, present: set, path: str) -> str:
    """
    Derive a readable company name from the file name.

    The workbook has no company-name cell, so this is the best source we
    have. We strip the period and CLEAN suffixes and split CamelCase, so
    "MeridianBank_FY2026_CLEAN.xlsx" reads as "Meridian Bank".
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"[_-]?(FY\d{2,4}|CLEAN|REVIEW)", "", stem, flags=re.IGNORECASE)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)       # MeridianBank -> Meridian Bank
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or "Unknown Company"
