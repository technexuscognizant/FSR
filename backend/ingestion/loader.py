"""
backend/ingestion/loader.py
===========================
The front door. Everyone else calls one function:

    from backend.ingestion.loader import load_statements

    data = load_statements("data/review/MeridianBank_FY2026.xlsx")
    data = load_statements(["Income_Statement.csv", "Balance_Sheet.csv", ...])

It accepts a single path or a list, works out which reader applies, runs it,
checks the result, and returns the canonical shape from statements.py.

TO ADD A FORMAT LATER
    Write a reader in readers/, then add one line to READERS below. Nothing
    else in the codebase changes, because nothing else ever touches a file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence, Union

from backend.ingestion.readers import meridian_csv, meridian_xlsx
from backend.ingestion.statements import StatementError

PathLike = Union[str, Sequence[str]]

# (name, does this reader handle these paths?, reader function)
READERS = [
    ("meridian_xlsx",
     lambda paths: len(paths) == 1 and meridian_xlsx.looks_like_workbook(paths[0]),
     lambda paths: meridian_xlsx.read(paths[0])),
    ("meridian_csv",
     lambda paths: meridian_csv.looks_like_csv_set(paths),
     lambda paths: meridian_csv.read(paths)),
]

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}


def _as_list(paths: PathLike) -> List[str]:
    return [paths] if isinstance(paths, str) else list(paths)


def load_statements(paths: PathLike) -> Dict[str, Any]:
    """
    Read financial statements from Excel or CSV into the canonical shape.

    Raises StatementError with a message written to be shown to the user —
    no stack traces, no Python type names.
    """
    files = _as_list(paths)
    if not files:
        raise StatementError("No file was provided.")

    missing = [p for p in files if not os.path.exists(p)]
    if missing:
        raise StatementError(f"File(s) not found: {missing}")

    extensions = {os.path.splitext(p)[1].lower() for p in files}
    unsupported = extensions - SUPPORTED_EXTENSIONS
    if unsupported:
        raise StatementError(
            f"Unsupported file type(s): {sorted(unsupported)}. "
            f"Upload {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    if len(extensions) > 1:
        raise StatementError(
            "Upload either one Excel workbook or a set of CSV files, "
            "not a mixture."
        )

    for _, handles, reader in READERS:
        if handles(files):
            return reader(files)

    raise StatementError(
        "This file was not recognised. Expected the fixed statement layout — "
        "download the sample template from the app and match its structure."
    )


def supported_formats() -> List[str]:
    """Used by the API and UI so the accepted formats are never hardcoded."""
    return [name for name, _, _ in READERS]