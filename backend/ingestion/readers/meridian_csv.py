"""
backend/ingestion/readers/meridian_csv.py
=========================================
Reads the same statement set from separate CSV files.

THE PROBLEM CSV CREATES
    A CSV holds exactly one table. Our statement set is six. So "accepts CSV"
    can only mean one thing: the user uploads several CSV files at once, one
    per statement, and we assemble them.

HOW WE KNOW WHICH FILE IS WHICH
    Not by filename — a user may rename anything. We look inside. Each file's
    row labels are scored against each statement's expected vocabulary, and
    the best scoring match wins, provided it clears a threshold.

    That means "bs_final_v3.csv" is still recognised as the balance sheet,
    and a file that matches nothing is reported rather than guessed at.

MINIMUM TO PROCEED
    The three statements: income, balance, cash flow. Key_Ratios,
    Prior_Year_Published and Notes are optional — without them the ratio,
    prior-year and grammar checks simply report that they were skipped, which
    is honest and better than refusing the upload.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from backend.ingestion.statements import (
    STATEMENTS,
    StatementError,
    build_statement,
    clean_text,
    match_label,
    to_number,
    validate_shape,
)

SOURCE_FORMAT = "meridian_csv"
EXTENSIONS = {".csv"}

# A file must match at least this share of a statement's expected line items
# before we accept it as that statement. Below this we would be guessing.
CLASSIFY_THRESHOLD = 0.6

# A file that is not a full statement is treated as the prior-year block only
# if nearly all of its rows are recognised line items. This stops an unrelated
# spreadsheet from being quietly accepted as financial data.
RECOGNISE_THRESHOLD = 0.8


def looks_like_csv_set(paths: Sequence[str]) -> bool:
    return bool(paths) and all(
        os.path.splitext(p)[1].lower() in EXTENSIONS for p in paths)


# ── identifying what each file contains ──────────────────────────────────────

def _coverage(labels: List[str], expected: List[str]) -> float:
    """Share of a statement's expected line items that this file contains."""
    if not labels:
        return 0.0
    matched = sum(1 for item in expected
                  if any(match_label(label, [item])[0] for label in labels))
    return matched / len(expected)


def _recognition(labels: List[str]) -> float:
    """
    Share of this file's own rows that are recognised financial line items.

    Coverage and recognition answer different questions, and we need both.
    Prior_Year_Published holds only seven rows drawn from two statements, so
    its coverage against any one statement is low (~0.33) even though every
    row is a perfectly valid line item. Recognition catches that; coverage
    never would.
    """
    if not labels:
        return 0.0
    vocabulary = [item for _, items in STATEMENTS.values() for item in items]
    matched = sum(1 for label in labels if match_label(label, vocabulary)[0])
    return matched / len(labels)


def classify(path: str) -> tuple[Optional[str], float]:
    """
    Decide which statement a CSV holds by inspecting its contents, not its
    filename — a user may rename anything.

    Returns (key, score). Key is a statement key, or "ratios" / "prior_year" /
    "notes", or None when nothing fits well enough to be worth guessing.
    """
    try:
        raw = pd.read_csv(path)
    except Exception:
        return None, 0.0
    if raw.empty:
        return None, 0.0

    columns = [clean_text(c) for c in raw.columns]

    # The two supporting sheets announce themselves in their first column.
    if columns and columns[0] == "Metric":
        return "ratios", 1.0
    if columns and columns[0] == "Note":
        return "notes", 1.0

    labels = [clean_text(v) for v in raw.iloc[:, 0]]

    best_key, best_coverage = None, 0.0
    for key, (_, expected) in STATEMENTS.items():
        score = _coverage(labels, expected)
        if score > best_coverage:
            best_key, best_coverage = key, score

    if best_coverage >= CLASSIFY_THRESHOLD:
        return best_key, best_coverage

    # Not a full statement, but if nearly every row is a real line item this
    # is the prior-year comparative block.
    recognised = _recognition(labels)
    if recognised >= RECOGNISE_THRESHOLD:
        return "prior_year", recognised

    return None, best_coverage


# ── reading ──────────────────────────────────────────────────────────────────

def read(paths: Sequence[str]) -> Dict[str, Any]:
    """Assemble one canonical statement set from several CSV files."""
    missing_files = [p for p in paths if not os.path.exists(p)]
    if missing_files:
        raise StatementError(f"File(s) not found: {missing_files}")

    found: Dict[str, str] = {}
    unrecognised: List[str] = []

    for path in paths:
        key, _ = classify(path)
        if key is None:
            unrecognised.append(os.path.basename(path))
        elif key not in found:
            found[key] = path

    absent = [key for key in STATEMENTS if key not in found]
    if absent:
        names = ", ".join(STATEMENTS[key][0] for key in absent)
        detail = (f" Unrecognised file(s): {unrecognised}."
                  if unrecognised else "")
        raise StatementError(
            f"Missing required statement(s): {names}. Upload one CSV per "
            f"statement.{detail}"
        )

    statements: Dict[str, pd.DataFrame] = {}
    label_issues: List[Dict[str, Any]] = []
    years: List[str] = []

    for key, (sheet_name, expected) in STATEMENTS.items():
        raw = pd.read_csv(found[key])
        sheet_years = [clean_text(c) for c in raw.columns[1:]
                       if clean_text(c).upper().startswith("FY")]
        if not sheet_years:
            raise StatementError(
                f"'{os.path.basename(found[key])}' has no FY columns.")
        years = years or sheet_years

        rows = [(row.iloc[0], [row[year] for year in sheet_years])
                for _, row in raw.iterrows()]
        frame, issues = build_statement(rows, sheet_years, expected, sheet_name)
        statements[key] = frame
        label_issues.extend(issues)

    payload = {
        "company_name": _company_name(paths),
        "source_file": ", ".join(sorted(os.path.basename(p) for p in paths)),
        "source_format": SOURCE_FORMAT,
        "years": years,
        "statements": statements,
        "ratios": _optional_ratios(found.get("ratios"), years),
        "prior_year": _optional_prior_year(found.get("prior_year")),
        "notes": _optional_notes(found.get("notes")),
        "label_issues": label_issues,
    }
    validate_shape(payload)
    return payload


def _optional_ratios(path: Optional[str], years: List[str]) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["Metric"] = frame["Metric"].map(clean_text)
    frame = frame.set_index("Metric")
    for year in years:
        if year in frame.columns:
            frame[year] = frame[year].map(to_number)
    return frame


def _optional_prior_year(path: Optional[str]) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["Particular"] = frame["Particular"].map(clean_text)
    frame = frame.set_index("Particular")
    for column in frame.columns:
        frame[column] = frame[column].map(to_number)
    return frame


def _optional_notes(path: Optional[str]) -> List[Dict[str, str]]:
    if not path:
        return []
    frame = pd.read_csv(path)
    return [{"note": clean_text(row.iloc[0]), "text": clean_text(row.iloc[1])}
            for _, row in frame.iterrows() if clean_text(row.iloc[1])]


def _company_name(paths: Sequence[str]) -> str:
    """
    CSVs carry no company name, so we use the folder they came from — which
    for our dataset is 'clean' or 'review'. Falls back to a placeholder the
    user can see is a placeholder, rather than inventing a name.
    """
    folder = os.path.basename(os.path.dirname(os.path.abspath(paths[0])))
    if folder and folder.lower() not in ("csv", "clean", "review", "data", ""):
        return folder.replace("_", " ")
    return "Uploaded Statements"