"""
tests/test_statements_ingestion.py
==================================
Tests for the fixed-schema readers (Excel and CSV).

Both readers must produce an identical canonical structure from the same
underlying data — that equivalence is what lets everything downstream ignore
the file format entirely, and it is asserted directly below.

Run:  python -m pytest tests/ -v
"""

import glob
import os
import shutil

import pytest

from backend.ingestion.loader import load_statements, supported_formats
from backend.ingestion.readers.meridian_csv import classify
from backend.ingestion.statements import (
    BALANCE_ITEMS,
    CASH_FLOW_ITEMS,
    INCOME_ITEMS,
    StatementError,
    match_label,
    to_number,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

CLEAN_XLSX = os.path.join(DATA, "clean", "MeridianBank_FY2026_CLEAN.xlsx")
REVIEW_XLSX = os.path.join(DATA, "review", "MeridianBank_FY2026.xlsx")
CLEAN_CSVS = sorted(glob.glob(os.path.join(DATA, "clean", "csv", "*.csv")))
REVIEW_CSVS = sorted(glob.glob(os.path.join(DATA, "review", "csv", "*.csv")))

dataset_exists = pytest.mark.skipif(
    not os.path.exists(REVIEW_XLSX),
    reason="Run 'python tools/make_dataset.py' first.",
)


@pytest.fixture(scope="module")
def review():
    return load_statements(REVIEW_XLSX)


@pytest.fixture(scope="module")
def clean():
    return load_statements(CLEAN_XLSX)


# ═══════════════════════════════════════════════════════════════════════════
# Shape
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
@pytest.mark.parametrize("path", [CLEAN_XLSX, REVIEW_XLSX])
def test_workbook_produces_the_canonical_shape(path):
    data = load_statements(path)
    for key in ("company_name", "source_file", "source_format", "years",
                "statements", "ratios", "prior_year", "notes", "label_issues"):
        assert key in data
    assert data["source_format"] == "meridian_xlsx"
    assert data["years"] == ["FY2024", "FY2025", "FY2026"]


@dataset_exists
def test_all_three_statements_are_present_and_complete(review):
    for key, expected in (("income", INCOME_ITEMS),
                          ("balance", BALANCE_ITEMS),
                          ("cash_flow", CASH_FLOW_ITEMS)):
        frame = review["statements"][key]
        assert list(frame.index) == expected
        assert list(frame.columns) == ["FY2024", "FY2025", "FY2026"]


@dataset_exists
def test_supporting_sheets_are_read(review):
    assert "Return on equity %" in review["ratios"].index
    assert "Basis" in review["ratios"].columns
    assert "Deposits" in review["prior_year"].index
    assert len(review["notes"]) == 6


@dataset_exists
def test_known_values_are_exact(review):
    balance = review["statements"]["balance"]
    income = review["statements"]["income"]
    assert balance.loc["Total assets", "FY2026"] == 758410
    assert balance.loc["Total liabilities and equity", "FY2026"] == 756110
    assert income.loc["Interest income", "FY2024"] == 48200
    assert income.loc["Basic earnings per share", "FY2026"] == 18.49


# ═══════════════════════════════════════════════════════════════════════════
# Misspelled labels — normalised AND reported
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_clean_file_has_no_label_issues(clean):
    assert clean["label_issues"] == []


@dataset_exists
def test_all_three_planted_typos_are_found(review):
    found = {issue["found"] for issue in review["label_issues"]}
    assert found == {"Provisons and contingencies",
                     "Reserves and surpluss",
                     "Dividends payed"}


@dataset_exists
def test_each_typo_suggests_the_right_correction(review):
    corrections = {i["found"]: i["suggestion"] for i in review["label_issues"]}
    assert corrections["Provisons and contingencies"] == "Provisions and contingencies"
    assert corrections["Reserves and surpluss"] == "Reserves and surplus"
    assert corrections["Dividends payed"] == "Dividends paid"


@dataset_exists
def test_a_misspelled_row_still_has_its_numbers_read(review):
    """
    'Reserves and surpluss' is misspelled AND numerically wrong. If fuzzy
    matching failed, the row would go missing and the numeric defect would
    never be found. Both must work at once.
    """
    assert review["statements"]["balance"].loc["Reserves and surplus", "FY2025"] == 49300


@dataset_exists
def test_label_issues_record_where_they_were_found(review):
    for issue in review["label_issues"]:
        assert issue["sheet"] in ("Income_Statement", "Balance_Sheet", "Cash_Flow")
        assert issue["row"] > 1
        assert 0 < issue["similarity"] <= 1


def test_match_label_accepts_near_misses_and_rejects_different_items():
    assert match_label("Provisons and contingencies", INCOME_ITEMS)[0] == \
           "Provisions and contingencies"
    assert match_label("total assets", BALANCE_ITEMS)[0] == "Total assets"
    assert match_label("Bananas", BALANCE_ITEMS)[0] is None


def test_match_label_does_not_confuse_similar_but_distinct_rows():
    """
    'Total liabilities' and 'Total liabilities and equity' are different rows.
    Collapsing them would silently attach numbers to the wrong line.
    """
    assert match_label("Total liabilities", BALANCE_ITEMS)[0] == "Total liabilities"
    assert match_label("Total liabilities and equity", BALANCE_ITEMS)[0] == \
           "Total liabilities and equity"


# ═══════════════════════════════════════════════════════════════════════════
# Numbers
# ═══════════════════════════════════════════════════════════════════════════

def test_to_number_handles_the_formats_a_spreadsheet_produces():
    assert to_number("1,234") == 1234
    assert to_number("(500)") == -500          # accounting negative
    assert to_number("12.5%") == 12.5
    assert to_number(" 42 ") == 42


def test_missing_values_stay_none_and_never_become_zero():
    """A blank cell is unknown, not zero. Zero would be a confident lie."""
    for blank in (None, "", "-", "n/a", "abc"):
        assert to_number(blank) is None


# ═══════════════════════════════════════════════════════════════════════════
# CSV — several files, assembled into one statement set
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_every_csv_is_classified_by_content(review):
    expected = {
        "Income_Statement.csv": "income",
        "Balance_Sheet.csv": "balance",
        "Cash_Flow.csv": "cash_flow",
        "Key_Ratios.csv": "ratios",
        "Prior_Year_Published.csv": "prior_year",
        "Notes.csv": "notes",
    }
    for path in REVIEW_CSVS:
        key, _ = classify(path)
        assert key == expected[os.path.basename(path)]


@dataset_exists
def test_csv_set_loads(review):
    data = load_statements(REVIEW_CSVS)
    assert data["source_format"] == "meridian_csv"
    assert data["years"] == ["FY2024", "FY2025", "FY2026"]


@dataset_exists
def test_excel_and_csv_produce_identical_numbers(review):
    """
    The equivalence everything downstream depends on. If these ever diverge,
    a user gets different answers from the same data in a different wrapper.
    """
    from_csv = load_statements(REVIEW_CSVS)
    for key in ("income", "balance", "cash_flow"):
        assert review["statements"][key].equals(from_csv["statements"][key])
    assert review["notes"] == from_csv["notes"]
    assert len(review["label_issues"]) == len(from_csv["label_issues"])


@dataset_exists
def test_renamed_csv_files_are_still_recognised(tmp_path):
    """Classification reads contents, not filenames."""
    for index, source in enumerate(REVIEW_CSVS):
        shutil.copy(source, tmp_path / f"upload_{index}.csv")
    data = load_statements(sorted(str(p) for p in tmp_path.glob("*.csv")))
    assert data["statements"]["balance"].loc["Total assets", "FY2026"] == 758410


@dataset_exists
def test_supporting_csvs_are_optional(tmp_path):
    """
    Upload only the three statements and the tool still works — the ratio,
    prior-year and grammar checks just have nothing to run on.
    """
    for source in REVIEW_CSVS:
        if any(k in source for k in ("Income", "Balance", "Cash")):
            shutil.copy(source, tmp_path / os.path.basename(source))
    data = load_statements(sorted(str(p) for p in tmp_path.glob("*.csv")))
    assert data["ratios"].empty
    assert data["prior_year"].empty
    assert data["notes"] == []
    assert data["statements"]["income"].loc["Total income", "FY2026"] == 34875


@dataset_exists
def test_missing_a_required_statement_is_rejected_clearly(tmp_path):
    for source in REVIEW_CSVS:
        if "Income" in source or "Balance" in source:
            shutil.copy(source, tmp_path / os.path.basename(source))
    with pytest.raises(StatementError) as error:
        load_statements(sorted(str(p) for p in tmp_path.glob("*.csv")))
    assert "Cash_Flow" in str(error.value)


def test_unrelated_csv_is_not_mistaken_for_a_statement(tmp_path):
    junk = tmp_path / "shopping.csv"
    junk.write_text("Particular,FY2024\nBananas,5\nApples,7\n")
    assert classify(str(junk))[0] is None


# ═══════════════════════════════════════════════════════════════════════════
# Failure handling
# ═══════════════════════════════════════════════════════════════════════════

def test_missing_file_is_rejected():
    with pytest.raises(StatementError):
        load_statements("nope.xlsx")


def test_unsupported_extension_is_rejected(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(StatementError) as error:
        load_statements(str(bad))
    assert ".txt" in str(error.value)


def test_mixing_excel_and_csv_in_one_upload_is_rejected(tmp_path):
    if not os.path.exists(REVIEW_XLSX):
        pytest.skip("dataset not generated")
    csv_copy = tmp_path / "Income_Statement.csv"
    shutil.copy(REVIEW_CSVS[0], csv_copy)
    with pytest.raises(StatementError) as error:
        load_statements([REVIEW_XLSX, str(csv_copy)])
    assert "mixture" in str(error.value).lower()


def test_workbook_missing_a_sheet_is_rejected(tmp_path):
    import pandas as pd
    partial = tmp_path / "partial.xlsx"
    with pd.ExcelWriter(partial) as writer:
        pd.DataFrame({"Particular": ["Interest income"], "FY2024": [1]}).to_excel(
            writer, sheet_name="Income_Statement", index=False)
    with pytest.raises(StatementError):
        load_statements(str(partial))


@dataset_exists
def test_reader_releases_the_file_handle(tmp_path):
    """
    Windows cannot delete a file that is still open, and the API deletes every
    upload right after parsing. Deleting here proves the handle was released.
    """
    copy = tmp_path / "book.xlsx"
    shutil.copy(REVIEW_XLSX, copy)
    load_statements(str(copy))
    os.unlink(copy)
    assert not copy.exists()


def test_supported_formats_are_advertised():
    assert "meridian_xlsx" in supported_formats()
    assert "meridian_csv" in supported_formats()