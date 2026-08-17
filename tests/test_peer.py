"""
tests/test_peer.py
==================
Peer benchmarking. The important assertions here are about JUDGEMENT, not
arithmetic: that we recompute rather than quote, that "better" is only
declared where better is defined, and that the two banks genuinely lead on
different things.
"""

import os

import pytest

from backend.ingestion.loader import load_statements
from backend.review.peer import (
    compare_statements,
    compute_metrics,
    _divide,
    _growth,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERIDIAN = os.path.join(ROOT, "data", "clean", "MeridianBank_FY2026_CLEAN.xlsx")
STERLING = os.path.join(ROOT, "data", "clean", "SterlingBank_FY2026_CLEAN.xlsx")

dataset_exists = pytest.mark.skipif(
    not os.path.exists(STERLING), reason="Run tools/make_dataset.py first.")


@pytest.fixture(scope="module")
def comparison():
    return compare_statements(load_statements(MERIDIAN), load_statements(STERLING))


# ── arithmetic guards ────────────────────────────────────────────────────────

def test_divide_returns_none_never_zero_or_infinity():
    """A ratio with a zero denominator is unknown, not zero."""
    assert _divide(10, 0) is None
    assert _divide(None, 5) is None
    assert _divide(10, 4) == 2.5


def test_growth_is_undefined_for_non_positive_values():
    """A company going from a loss to a profit has no meaningful CAGR."""
    assert _growth([-50, 100]) is None
    assert _growth([0, 100]) is None
    assert _growth([100]) is None
    assert _growth([100, 121]) == pytest.approx(0.21, abs=1e-9)


def test_growth_uses_the_right_number_of_intervals():
    """Three data points span two years of growth, not three."""
    assert _growth([100, 150, 225]) == pytest.approx(0.5, abs=1e-9)


# ── recomputation, not quotation ─────────────────────────────────────────────

@dataset_exists
def test_ratios_are_recomputed_not_read_from_the_published_sheet():
    """
    The whole point of the tool. We derive our own figure from the
    statements; the bank's own Key_Ratios sheet is never the source.
    """
    data = load_statements(MERIDIAN)
    computed = compute_metrics(data)["metrics"]

    income = data["statements"]["income"]
    balance = data["statements"]["balance"]
    expected_roe = (income.loc["Profit for the year", "FY2026"]
                    / balance.loc["Total equity", "FY2026"])
    assert computed["roe_pct"] == pytest.approx(expected_roe, abs=1e-9)


@dataset_exists
def test_percentages_are_fractions_not_whole_numbers():
    """0.1929 means 19.29%. Formatting happens at the edge, not here."""
    metrics = compute_metrics(load_statements(MERIDIAN))["metrics"]
    assert 0 < metrics["roe_pct"] < 1
    assert 0 < metrics["cost_to_income_pct"] < 1


# ── comparison shape ─────────────────────────────────────────────────────────

@dataset_exists
def test_both_companies_appear(comparison):
    assert comparison["companies"] == ["Meridian Bank", "Sterling Bank"]
    assert comparison["comparison_year"] == "FY2026"


@dataset_exists
def test_every_metric_has_a_value_for_both(comparison):
    for row in comparison["metrics"]:
        assert set(row["values"]) == set(comparison["companies"])


@dataset_exists
def test_higher_is_better_picks_the_larger_value(comparison):
    row = next(r for r in comparison["metrics"] if r["key"] == "roe_pct")
    assert row["leader"] == max(row["values"], key=lambda n: row["values"][n])


@dataset_exists
def test_lower_is_better_is_inverted(comparison):
    """Cost-to-income and credit cost are better when smaller."""
    for key in ("cost_to_income_pct", "credit_cost_pct"):
        row = next(r for r in comparison["metrics"] if r["key"] == key)
        assert row["higher_is_better"] is False
        assert row["leader"] == min(row["values"], key=lambda n: row["values"][n])


@dataset_exists
def test_no_leader_where_better_is_undefined(comparison):
    """A higher tax rate is not a virtue; lending ratio is a strategy choice."""
    for key in ("effective_tax_pct", "credit_deposit_pct"):
        row = next(r for r in comparison["metrics"] if r["key"] == key)
        assert row["higher_is_better"] is None
        assert row["leader"] is None


@dataset_exists
def test_scorecard_wins_sum_to_metrics_scored(comparison):
    scorecard = comparison["scorecard"]
    assert sum(scorecard["wins"].values()) == scorecard["metrics_scored"]


# ── the comparison is actually interesting ───────────────────────────────────

@dataset_exists
def test_the_two_banks_lead_on_different_things(comparison):
    """
    A benchmarking page where one company wins everything shows nothing.
    Meridian is the larger, more profitable, more efficient bank; Sterling
    is smaller and growing much faster. Both must win something.
    """
    wins = comparison["scorecard"]["wins"]
    assert all(count > 0 for count in wins.values())

    leaders = {r["key"]: r["leader"] for r in comparison["metrics"]}
    assert leaders["roe_pct"] == "Meridian Bank"
    assert leaders["cost_to_income_pct"] == "Meridian Bank"
    for key in ("income_cagr", "profit_cagr", "advances_cagr", "deposits_cagr"):
        assert leaders[key] == "Sterling Bank"


# ── failure handling ─────────────────────────────────────────────────────────

@dataset_exists
def test_comparing_fewer_than_two_companies_is_rejected():
    with pytest.raises(ValueError):
        compare_statements(load_statements(MERIDIAN))


@dataset_exists
def test_comparing_a_company_with_itself_is_rejected():
    data = load_statements(MERIDIAN)
    with pytest.raises(ValueError):
        compare_statements(data, load_statements(MERIDIAN))


@dataset_exists
def test_result_is_json_serialisable(comparison):
    import json
    json.dumps(comparison)
