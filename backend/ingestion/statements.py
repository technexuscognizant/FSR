"""
backend/ingestion/statements.py
===============================
The canonical shape for fixed-schema financial statements, and the vocabulary
of line items we expect to find.

WHAT "CANONICAL" MEANS HERE
    Whatever the input was — one Excel workbook, or six separate CSV files —
    every reader produces this same structure. Nothing downstream (validation,
    ratios, WP-514, the UI) ever knows which it was.

    {
      "company_name":  "Meridian Commercial Bank Limited",
      "source_format": "meridian_xlsx",
      "years":         ["FY2024", "FY2025", "FY2026"],
      "statements": {
          "income":     DataFrame,   rows = line item, cols = years
          "balance":    DataFrame,
          "cash_flow":  DataFrame,
      },
      "ratios":      DataFrame,   published ratios + their stated Basis
      "prior_year":  DataFrame,   figures as filed last year
      "notes":       [{"note": "N1", "text": "..."}],
      "label_issues": [ ... ]     misspelled row labels found while reading
    }

THE VOCABULARY IS THE POINT
    Because the schema is fixed, we know every label that SHOULD appear. That
    single fact gives us two things at once:

      1. Reading is trivial — look the row up by name.
      2. Spelling checking is free — any label that is close to an expected
         one but not equal to it is a typo. No dictionary, no NLP library,
         no false alarms on finance jargon.

    So the reader normalises "Reserves and surpluss" to "Reserves and surplus"
    AND records the typo. One pass, two requirements from the brief.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

import pandas as pd

# How similar a label must be to an expected one before we accept it as a
# misspelling of that item. 0.85 catches single-letter slips like
# "Provisons"/"Provisions" without confusing genuinely different rows such as
# "Total liabilities" and "Total liabilities and equity".
LABEL_MATCH_CUTOFF = 0.85


class StatementError(Exception):
    """The file could not be read as a financial statement set."""


# ── expected line items, in the order they appear ────────────────────────────

INCOME_ITEMS = [
    "Interest income",
    "Interest expense",
    "Net interest income",
    "Fee and commission income",
    "Treasury and other income",
    "Total other income",
    "Total income",
    "Employee cost",
    "Depreciation and amortisation",
    "Other operating expenses",
    "Total operating expenses",
    "Operating profit before provisions",
    "Provisions and contingencies",
    "Profit before tax",
    "Tax expense",
    "Profit for the year",
    "Number of equity shares (crore)",
    "Diluted equity shares (crore)",
    "Basic earnings per share",
    "Diluted earnings per share",
]

BALANCE_ITEMS = [
    "Cash and balances with RBI",
    "Balances with banks and money at call",
    "Investments",
    "Advances",
    "Fixed assets",
    "Other assets",
    "Total assets",
    "Deposits",
    "Borrowings",
    "Other liabilities and provisions",
    "Total liabilities",
    "Share capital",
    "Reserves and surplus",
    "Total equity",
    "Total liabilities and equity",
]

CASH_FLOW_ITEMS = [
    "Profit for the year",
    "Depreciation and amortisation",
    "Provisions and contingencies",
    "Changes in working capital and other items",
    "Net cash from operating activities",
    "Purchase of fixed assets",
    "Net investment in securities",
    "Net cash from investing activities",
    "Proceeds from issue of share capital",
    "Repayment of borrowings",
    "Dividends paid",
    "Net cash from financing activities",
    "Net increase in cash and cash equivalents",
    "Opening cash and cash equivalents",
    "Closing cash and cash equivalents",
]

STATEMENTS = {
    "income": ("Income_Statement", INCOME_ITEMS),
    "balance": ("Balance_Sheet", BALANCE_ITEMS),
    "cash_flow": ("Cash_Flow", CASH_FLOW_ITEMS),
}

SUPPORTING_SHEETS = ["Key_Ratios", "Prior_Year_Published", "Notes"]

REQUIRED_KEYS = [
    "company_name", "source_file", "source_format", "years",
    "statements", "ratios", "prior_year", "notes", "label_issues",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def clean_text(value: Any) -> str:
    """Collapse whitespace. '  Total   assets ' -> 'Total assets'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def to_number(value: Any) -> Optional[float]:
    """
    Anything -> float, or None when there is no number.

    None means unknown, and stays None. Returning 0.0 for a blank cell would
    put a confident wrong figure into every calculation downstream.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "").replace("₹", "").rstrip("%")
    if text in ("", "-", "--", "n/a", "N/A", "nan", "None"):
        return None
    if text.startswith("(") and text.endswith(")"):      # (123) means -123
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def match_label(found: str, expected: List[str]) -> tuple[Optional[str], float]:
    """
    Map a label from the file onto our expected vocabulary.

    Returns (canonical label or None, similarity 0-1). An exact match scores
    1.0. A near match is accepted and reported. Anything below the cutoff is
    rejected rather than guessed at — a wrong guess would silently attach
    numbers to the wrong line item, which is worse than failing loudly.
    """
    if found in expected:
        return found, 1.0

    lowered = {item.lower(): item for item in expected}
    if found.lower() in lowered:
        return lowered[found.lower()], 1.0

    close = difflib.get_close_matches(found, expected, n=1,
                                      cutoff=LABEL_MATCH_CUTOFF)
    if close:
        similarity = difflib.SequenceMatcher(None, found, close[0]).ratio()
        return close[0], round(similarity, 3)

    return None, 0.0


def build_statement(rows: List[tuple], years: List[str], expected: List[str],
                    sheet_name: str) -> tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Turn raw (label, values) rows into a tidy frame keyed by canonical label.

    Returns the frame and any misspellings found. Duplicate labels keep the
    first occurrence, so a stray repeated row cannot silently overwrite real
    data.
    """
    data: Dict[str, List[Optional[float]]] = {}
    issues: List[Dict[str, Any]] = []

    for position, (raw_label, values) in enumerate(rows):
        label = clean_text(raw_label)
        if not label:
            continue

        canonical, similarity = match_label(label, expected)
        if canonical is None:
            issues.append({
                "sheet": sheet_name, "row": position + 2, "found": label,
                "suggestion": None, "similarity": 0.0, "kind": "unknown_label",
            })
            continue

        if canonical != label:
            issues.append({
                "sheet": sheet_name, "row": position + 2, "found": label,
                "suggestion": canonical, "similarity": similarity,
                "kind": "misspelled_label",
            })

        if canonical not in data:
            data[canonical] = [to_number(v) for v in values]

    missing = [item for item in expected if item not in data]
    if missing:
        raise StatementError(
            f"'{sheet_name}' is missing required line item(s): {missing[:5]}"
            + (" …" if len(missing) > 5 else "")
        )

    frame = pd.DataFrame(data, index=years).T
    frame.index.name = "Particular"
    return frame, issues


def validate_shape(payload: Dict[str, Any]) -> None:
    """
    Confirm a reader produced a complete structure.

    Called at the end of every reader so a broken reader fails right there,
    with a clear message, instead of three modules later where the error
    would make no sense.
    """
    missing = [key for key in REQUIRED_KEYS if key not in payload]
    if missing:
        raise StatementError(f"Reader returned an incomplete structure. "
                             f"Missing: {missing}")

    for key in STATEMENTS:
        if key not in payload["statements"]:
            raise StatementError(f"Missing statement: '{key}'")

    if not payload["years"]:
        raise StatementError("No fiscal year columns were found.")