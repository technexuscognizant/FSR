"""
tests/test_review_engine.py
===========================
Tests for the fixed-schema review engine.

Two halves:

  POSITIVE — the clean file must come back with zero exceptions. A reviewer
             that flags healthy statements is unusable.

  NEGATIVE — every one of the 13 planted defects must be caught, at the
             right severity, in the right period, with the right magnitude.
             Driven directly by data/EXPECTED_FINDINGS.json, so regenerating
             the dataset automatically updates what we assert here.

Run:
    python tools/make_dataset.py     (once, to create the dataset)
    python -m pytest tests/ -v
"""

import json
import os

import pytest

from backend.ingestion.loader import load_statements
from backend.review.engine import FAIL, INFO, PASS, WARN, StatementReviewEngine, review_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CLEAN = os.path.join(DATA, "clean", "MeridianBank_FY2026_CLEAN.xlsx")
REVIEW = os.path.join(DATA, "review", "MeridianBank_FY2026.xlsx")
ANSWER_KEY = os.path.join(DATA, "EXPECTED_FINDINGS.json")

dataset_exists = pytest.mark.skipif(
    not os.path.exists(ANSWER_KEY),
    reason="Run 'python tools/make_dataset.py' first.",
)


def load_manifest():
    with open(ANSWER_KEY) as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def clean_report():
    return review_file(CLEAN)


@pytest.fixture(scope="module")
def review_report():
    return review_file(REVIEW)


def findings_for(report, check_id, period=None):
    matches = [f for f in report["findings"] if f["check_id"] == check_id]
    if period is not None:
        matches = [f for f in matches if f["period"] == period]
    return matches


# ═══════════════════════════════════════════════════════════════════════════
# POSITIVE — the clean file
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_clean_file_has_zero_failures(clean_report):
    assert clean_report["summary"]["FAIL"] == 0
    assert clean_report["summary"]["WARN"] == 0
    assert clean_report["verdict"] == "CLEAN"


@dataset_exists
def test_clean_file_runs_every_category(clean_report):
    categories = {f["category"] for f in clean_report["findings"]}
    assert any(c.startswith("A.") for c in categories)
    assert any(c.startswith("B.") for c in categories)
    assert any(c.startswith("C.") for c in categories)
    assert any(c.startswith("D.") for c in categories)


@dataset_exists
def test_clean_file_has_no_label_or_text_issues(clean_report):
    assert not findings_for(clean_report, "SPELL_LABEL")
    assert not findings_for(clean_report, "SPELL_NOTE")
    assert not findings_for(clean_report, "GRAMMAR_NOTE")


@dataset_exists
def test_clean_file_balance_sheet_balances_every_year(clean_report):
    for finding in findings_for(clean_report, "BS_BALANCE"):
        assert finding["status"] == PASS


# ═══════════════════════════════════════════════════════════════════════════
# NEGATIVE — every planted defect, driven by the answer key
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_every_numeric_defect_is_caught(review_report):
    manifest = load_manifest()
    numeric_kinds = {"math", "consistency", "prior_year", "ratio"}

    for defect in manifest["defects"]:
        if defect["kind"] not in numeric_kinds:
            continue
        for check_id in defect["expected_checks"]:
            matches = findings_for(review_report, check_id, defect.get("year"))
            assert matches, (
                f"{defect['id']}: no finding for {check_id} in "
                f"{defect.get('year')}"
            )
            finding = matches[0]
            assert finding["status"] == defect["severity"], (
                f"{defect['id']} {check_id}: expected {defect['severity']}, "
                f"got {finding['status']}"
            )


@dataset_exists
def test_every_spelling_defect_is_caught(review_report):
    manifest = load_manifest()
    found_typos = {f["found"] for f in findings_for(review_report, "SPELL_LABEL")}
    found_note_typos = {f["found"] for f in findings_for(review_report, "SPELL_NOTE")}

    for defect in manifest["defects"]:
        if defect["kind"] == "spelling" and defect["sheet"] != "Notes":
            assert defect["corrupted_value"] in found_typos, (
                f"{defect['id']}: '{defect['corrupted_value']}' not flagged"
            )
        elif defect["kind"] == "spelling" and defect["sheet"] == "Notes":
            assert found_note_typos, f"{defect['id']}: no note misspelling flagged"


@dataset_exists
def test_the_grammar_defect_is_caught(review_report):
    assert findings_for(review_report, "GRAMMAR_NOTE")


@dataset_exists
def test_review_file_verdict_is_exceptions_found(review_report):
    assert review_report["verdict"] == "EXCEPTIONS FOUND"
    assert review_report["summary"]["FAIL"] >= 10


# ═══════════════════════════════════════════════════════════════════════════
# Specific defects, asserted by exact value — belt and braces beyond the
# manifest-driven loop above
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_d01_opex_cascades_into_operating_profit(review_report):
    opex = findings_for(review_report, "IS_TOTAL_OPEX", "FY2026")[0]
    operating = findings_for(review_report, "IS_OPERATING_PROFIT", "FY2026")[0]
    assert opex["status"] == FAIL and opex["root_cause"] is True
    assert operating["status"] == FAIL and operating["root_cause"] is False


@dataset_exists
def test_d02_balance_sheet_fails_in_fy2026_only(review_report):
    for year, expected_status in (("FY2024", PASS), ("FY2025", PASS),
                                  ("FY2026", FAIL)):
        finding = findings_for(review_report, "BS_BALANCE", year)[0]
        assert finding["status"] == expected_status


@dataset_exists
def test_d03_is_caught_by_two_independent_checks(review_report):
    """One corrupted cell, found by the equity subtotal AND the prior-year
    tie-out — two unrelated routes converging on the same row."""
    equity = findings_for(review_report, "BS_EQUITY_COMPONENTS", "FY2025")[0]
    prior = findings_for(review_report, "PY_RESERVES_AND_SURPLUS", "FY2025")[0]
    assert equity["status"] == FAIL
    assert prior["status"] == FAIL
    assert abs(equity["delta"]) == pytest.approx(2700, abs=1)
    assert abs(prior["delta"]) == pytest.approx(2700, abs=1)


@dataset_exists
def test_d06_one_crore_is_a_warning_not_a_failure(review_report):
    """A tool that reds-out a 1 crore gap loses credibility fast."""
    net_change = findings_for(review_report, "CF_NET_CHANGE", "FY2024")[0]
    rollforward = findings_for(review_report, "CF_CLOSING_ROLLFORWARD", "FY2024")[0]
    assert net_change["status"] == WARN
    assert rollforward["status"] == WARN
    assert abs(net_change["delta"]) == 1
    assert review_report["summary"]["FAIL"] == 12   # WARN is not counted in FAIL


@dataset_exists
def test_d07_prior_year_only_current_checks_stay_clean(review_report):
    """
    FY2024 is internally perfect — every current-year check passes. Only the
    prior-year tie-out finds the restated deposits figure. This is the
    defect that justifies the whole module.
    """
    for check_id in ("BS_BALANCE", "BS_LIABILITY_COMPONENTS"):
        finding = findings_for(review_report, check_id, "FY2024")[0]
        assert finding["status"] == PASS

    prior = findings_for(review_report, "PY_DEPOSITS", "FY2024")[0]
    assert prior["status"] == FAIL
    assert prior["delta"] == pytest.approx(1400, abs=1)


@dataset_exists
def test_d10_misspelled_row_still_has_correct_numbers(review_report):
    """
    'Reserves and surpluss' is both a typo and numerically wrong. The engine
    must find both — a reader that lost the row to the misspelling would
    silently miss the numeric defect too.
    """
    typo = findings_for(review_report, "SPELL_LABEL")
    assert any(f["found"] == "Reserves and surpluss" for f in typo)
    numeric = findings_for(review_report, "BS_EQUITY_COMPONENTS", "FY2025")[0]
    assert numeric["status"] == FAIL


# ═══════════════════════════════════════════════════════════════════════════
# Missing supporting data is honest, not silently skipped as PASS
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_missing_prior_year_reports_info_not_pass():
    from backend.ingestion.loader import load_statements
    data = load_statements(REVIEW)
    data["prior_year"] = data["prior_year"].iloc[0:0]     # simulate absence
    report = StatementReviewEngine(data).run()
    finding = findings_for(report, "PY_NOT_SUPPLIED")[0]
    assert finding["status"] == INFO
    assert "skipped" in finding["note"].lower()


@dataset_exists
def test_missing_ratios_reports_info_not_pass():
    data = load_statements(REVIEW)
    data["ratios"] = data["ratios"].iloc[0:0]
    report = StatementReviewEngine(data).run()
    finding = findings_for(report, "RATIO_NOT_SUPPLIED")[0]
    assert finding["status"] == INFO


# ═══════════════════════════════════════════════════════════════════════════
# Output shape
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
def test_report_has_the_agreed_top_level_keys(review_report):
    for key in ("company_name", "source_file", "tolerance_crore",
               "periods_checked", "summary", "verdict", "findings"):
        assert key in review_report


@dataset_exists
def test_every_finding_has_the_agreed_fields(review_report):
    for finding in review_report["findings"]:
        for key in ("check_id", "category", "statement", "period", "rule",
                   "expected", "found", "delta", "status", "root_cause", "note"):
            assert key in finding


@dataset_exists
def test_summary_counts_add_up(review_report):
    summary = review_report["summary"]
    assert (summary["PASS"] + summary["WARN"] + summary["FAIL"] + summary["INFO"]
           ) == summary["total_checks"]


@dataset_exists
def test_report_is_json_serialisable(review_report):
    json.dumps(review_report)


@dataset_exists
def test_tolerance_is_configurable():
    data = load_statements(REVIEW)
    strict = StatementReviewEngine(data, tolerance=0.0).run()
    assert strict["tolerance_crore"] == 0.0

# ═══════════════════════════════════════════════════════════════════════════
# Every generated clean file must tie out — not just the one we demo
# ═══════════════════════════════════════════════════════════════════════════

@dataset_exists
@pytest.mark.parametrize("filename", [
    "MeridianBank_FY2026_CLEAN.xlsx",
    "SterlingBank_FY2026_CLEAN.xlsx",
])
def test_every_clean_company_passes_every_check(filename):
    """
    Regression guard.

    The dataset generator originally back-solved the cash flow for the first
    year only, leaving later years dependent on the typed working-capital
    figures happening to reconcile. That held by luck for one company and
    broke the moment a second was added — Sterling's clean file reported two
    false failures.

    Parametrising over every company means adding a third one cannot
    reintroduce the bug silently.
    """
    report = review_file(os.path.join(DATA, "clean", filename))
    failures = [f for f in report["findings"] if f["status"] in (FAIL, WARN)]
    assert not failures, (
        "clean file must have zero exceptions; got: "
        + "; ".join(f"{f['check_id']} {f['period']} delta {f['delta']}"
                    for f in failures)
    )
    assert report["verdict"] == "CLEAN"