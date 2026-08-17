"""
backend/review/engine.py
========================
The review engine for fixed-schema statements. Takes the canonical shape
from loader.py and produces a StatementReviewReport — every math check,
cross-sheet check, prior-year tie-out, ratio verification, and text issue,
in one structure.

    from backend.ingestion.loader import load_statements
    from backend.review.engine import StatementReviewEngine

    data = load_statements("data/review/MeridianBank_FY2026.xlsx")
    report = StatementReviewEngine(data).run()

    report["verdict"]              "EXCEPTIONS FOUND"
    report["summary"]["FAIL"]      11
    report["findings"]             every check, PASS and FAIL alike

NO AI ANYWHERE IN THIS FILE. Every number is computed by Python. This is the
deterministic engine the whole project's credibility rests on.

──────────────────────────────────────────────────────────────────────────
FIVE CATEGORIES, MATCHING THE PROBLEM STATEMENT LINE FOR LINE
──────────────────────────────────────────────────────────────────────────
  A. Mathematical accuracy        do the subtotals add up
  B. Internal consistency         do the statements agree with each other
  C. Prior year tie-out           do this year's comparatives match what
                                   was actually filed last year
  D. Ratio verification           do the published ratios match what we
                                   independently recompute
  E. Spelling and grammar         are the line-item labels and narrative
                                   text correct

──────────────────────────────────────────────────────────────────────────
FOUR STATUSES
──────────────────────────────────────────────────────────────────────────
  PASS   the check holds exactly
  WARN   off by no more than the tolerance — rounding, not a mistake
  FAIL   needs a human
  INFO   text observations (spelling/grammar) sit here, since "pass or
         fail" does not quite fit a suggestion

──────────────────────────────────────────────────────────────────────────
CASCADES
──────────────────────────────────────────────────────────────────────────
Corrupting Total operating expenses breaks three things at once: the opex
subtotal itself, operating profit (built on opex), and the published
cost-to-income ratio (computed from opex). Every affected check is reported,
but only the first carries root_cause=True. The rest say why they are
downstream, so a reviewer fixes one cell instead of chasing three.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

AMOUNT_TOLERANCE_CRORE = 2.0
RATIO_TOLERANCE_PP = 0.5          # percentage points

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


def _missing(*values) -> bool:
    return any(v is None or (isinstance(v, float) and pd.isna(v)) for v in values)


class StatementReviewEngine:
    def __init__(self, data: Dict[str, Any],
                 tolerance: float = AMOUNT_TOLERANCE_CRORE) -> None:
        self.data = data
        self.tolerance = tolerance
        self.income = data["statements"]["income"]
        self.balance = data["statements"]["balance"]
        self.cash_flow = data["statements"]["cash_flow"]
        self.ratios = data["ratios"]
        self.prior_year = data["prior_year"]
        self.notes = data["notes"]
        self.years: List[str] = data["years"]
        self.findings: List[Dict[str, Any]] = []

    # ── recording ────────────────────────────────────────────────────────────

    def _get(self, frame: pd.DataFrame, row: str, column: str) -> Optional[float]:
        if frame.empty or row not in frame.index or column not in frame.columns:
            return None
        value = frame.loc[row, column]
        return None if value is None or pd.isna(value) else float(value)

    def _record(self, *, check_id: str, category: str, statement: str,
               period: str, rule: str, expected: Optional[float],
               found: Optional[float], root_cause: bool = True,
               note: str = "") -> Dict[str, Any]:
        if _missing(expected, found):
            status, delta = INFO, None
            note = note or "Not enough data to run this check."
        else:
            delta = round(found - expected, 4)
            if delta == 0:
                status = PASS
            elif abs(delta) <= self.tolerance:
                status, note = WARN, note or (
                    f"Within the {self.tolerance:g} crore rounding tolerance.")
            else:
                status = FAIL

        finding = {
            "check_id": check_id, "category": category, "statement": statement,
            "period": period, "rule": rule,
            "expected": None if expected is None else round(expected, 4),
            "found": None if found is None else round(found, 4),
            "delta": delta, "status": status, "root_cause": root_cause,
            "note": note,
        }
        self.findings.append(finding)
        return finding

    # ── A. mathematical accuracy ─────────────────────────────────────────────

    def check_income_statement(self) -> None:
        for year in self.years:
            g = lambda row: self._get(self.income, row, year)

            self._record(
                check_id="IS_NII", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Net interest income = Interest income − Interest expense",
                expected=(None if _missing(g("Interest income"), g("Interest expense"))
                          else g("Interest income") - g("Interest expense")),
                found=g("Net interest income"),
            )
            self._record(
                check_id="IS_OTHER_INCOME", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Total other income = Fee income + Treasury income",
                expected=(None if _missing(g("Fee and commission income"),
                                           g("Treasury and other income"))
                          else g("Fee and commission income")
                          + g("Treasury and other income")),
                found=g("Total other income"),
            )
            self._record(
                check_id="IS_TOTAL_INCOME", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Total income = Net interest income + Total other income",
                expected=(None if _missing(g("Net interest income"), g("Total other income"))
                          else g("Net interest income") + g("Total other income")),
                found=g("Total income"),
            )

            opex_finding = self._record(
                check_id="IS_TOTAL_OPEX", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Total operating expenses = Employee cost + Depreciation + Other opex",
                expected=(None if _missing(g("Employee cost"), g("Depreciation and amortisation"),
                                           g("Other operating expenses"))
                          else g("Employee cost") + g("Depreciation and amortisation")
                          + g("Other operating expenses")),
                found=g("Total operating expenses"),
            )
            opex_broken = opex_finding["status"] == FAIL

            self._record(
                check_id="IS_OPERATING_PROFIT", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Operating profit = Total income − Total operating expenses",
                expected=(None if _missing(g("Total income"), g("Total operating expenses"))
                          else g("Total income") - g("Total operating expenses")),
                found=g("Operating profit before provisions"),
                root_cause=not opex_broken,
                note="Follows from the opex subtotal error above." if opex_broken else "",
            )
            self._record(
                check_id="IS_PBT", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Profit before tax = Operating profit − Provisions",
                expected=(None if _missing(g("Operating profit before provisions"),
                                           g("Provisions and contingencies"))
                          else g("Operating profit before provisions")
                          - g("Provisions and contingencies")),
                found=g("Profit before tax"),
            )
            self._record(
                check_id="IS_PAT", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Profit for the year = Profit before tax − Tax",
                expected=(None if _missing(g("Profit before tax"), g("Tax expense"))
                          else g("Profit before tax") - g("Tax expense")),
                found=g("Profit for the year"),
            )
            self._record(
                check_id="IS_EPS", category="A. Mathematical accuracy",
                statement="Income Statement", period=year,
                rule="Basic EPS = Profit for the year / Equity shares",
                expected=(None if _missing(g("Profit for the year"),
                                           g("Number of equity shares (crore)"))
                          or not g("Number of equity shares (crore)")
                          else round(g("Profit for the year")
                                     / g("Number of equity shares (crore)"), 2)),
                found=g("Basic earnings per share"),
            )

    def check_balance_sheet(self) -> None:
        for year in self.years:
            g = lambda row: self._get(self.balance, row, year)

            assets_finding = self._record(
                check_id="BS_ASSET_COMPONENTS", category="A. Mathematical accuracy",
                statement="Balance Sheet", period=year,
                rule="Total assets = sum of six asset lines",
                expected=(None if any(g(r) is None for r in (
                    "Cash and balances with RBI", "Balances with banks and money at call",
                    "Investments", "Advances", "Fixed assets", "Other assets"))
                    else sum(g(r) for r in (
                        "Cash and balances with RBI", "Balances with banks and money at call",
                        "Investments", "Advances", "Fixed assets", "Other assets"))),
                found=g("Total assets"),
            )
            liabilities_finding = self._record(
                check_id="BS_LIABILITY_COMPONENTS", category="A. Mathematical accuracy",
                statement="Balance Sheet", period=year,
                rule="Total liabilities = Deposits + Borrowings + Other liabilities",
                expected=(None if _missing(g("Deposits"), g("Borrowings"),
                                           g("Other liabilities and provisions"))
                          else g("Deposits") + g("Borrowings")
                          + g("Other liabilities and provisions")),
                found=g("Total liabilities"),
            )
            equity_finding = self._record(
                check_id="BS_EQUITY_COMPONENTS", category="A. Mathematical accuracy",
                statement="Balance Sheet", period=year,
                rule="Total equity = Share capital + Reserves and surplus",
                expected=(None if _missing(g("Share capital"), g("Reserves and surplus"))
                          else g("Share capital") + g("Reserves and surplus")),
                found=g("Total equity"),
            )

            subtotal_broken = FAIL in (liabilities_finding["status"],
                                       equity_finding["status"])
            self._record(
                check_id="BS_BALANCE", category="A. Mathematical accuracy",
                statement="Balance Sheet", period=year,
                rule="Total assets = Total liabilities + Total equity "
                     "(the balance sheet identity)",
                expected=(None if _missing(g("Total liabilities"), g("Total equity"))
                          else g("Total liabilities") + g("Total equity")),
                found=g("Total assets"),
                root_cause=not subtotal_broken,
                note=("Caused by the subtotal error above."
                      if subtotal_broken else
                      "A balance sheet that does not balance is the most "
                      "serious error a review can find."),
            )
            _ = assets_finding

    def check_cash_flow(self) -> None:
        for year in self.years:
            g = lambda row: self._get(self.cash_flow, row, year)

            self._record(
                check_id="CF_OPERATING_SUBTOTAL", category="A. Mathematical accuracy",
                statement="Cash Flow", period=year,
                rule="Operating cash flow = Profit + Depreciation + Provisions "
                     "+ Working capital change",
                expected=(None if any(g(r) is None for r in (
                    "Profit for the year", "Depreciation and amortisation",
                    "Provisions and contingencies",
                    "Changes in working capital and other items"))
                    else sum(g(r) for r in (
                        "Profit for the year", "Depreciation and amortisation",
                        "Provisions and contingencies",
                        "Changes in working capital and other items"))),
                found=g("Net cash from operating activities"),
            )
            self._record(
                check_id="CF_INVESTING_SUBTOTAL", category="A. Mathematical accuracy",
                statement="Cash Flow", period=year,
                rule="Investing cash flow = Fixed asset purchases + Net securities",
                expected=(None if _missing(g("Purchase of fixed assets"),
                                           g("Net investment in securities"))
                          else g("Purchase of fixed assets")
                          + g("Net investment in securities")),
                found=g("Net cash from investing activities"),
            )
            self._record(
                check_id="CF_FINANCING_SUBTOTAL", category="A. Mathematical accuracy",
                statement="Cash Flow", period=year,
                rule="Financing cash flow = Share issuance + Borrowing "
                     "repayment + Dividends paid",
                expected=(None if any(g(r) is None for r in (
                    "Proceeds from issue of share capital", "Repayment of borrowings",
                    "Dividends paid"))
                    else sum(g(r) for r in (
                        "Proceeds from issue of share capital",
                        "Repayment of borrowings", "Dividends paid"))),
                found=g("Net cash from financing activities"),
            )

            change_finding = self._record(
                check_id="CF_NET_CHANGE", category="A. Mathematical accuracy",
                statement="Cash Flow", period=year,
                rule="Net change = Operating + Investing + Financing",
                expected=(None if any(g(r) is None for r in (
                    "Net cash from operating activities",
                    "Net cash from investing activities",
                    "Net cash from financing activities"))
                    else sum(g(r) for r in (
                        "Net cash from operating activities",
                        "Net cash from investing activities",
                        "Net cash from financing activities"))),
                found=g("Net increase in cash and cash equivalents"),
            )
            self._record(
                check_id="CF_CLOSING_ROLLFORWARD", category="A. Mathematical accuracy",
                statement="Cash Flow", period=year,
                rule="Closing cash = Opening cash + Net change",
                expected=(None if _missing(g("Opening cash and cash equivalents"),
                                           g("Net increase in cash and cash equivalents"))
                          else g("Opening cash and cash equivalents")
                          + g("Net increase in cash and cash equivalents")),
                found=g("Closing cash and cash equivalents"),
                root_cause=change_finding["status"] != FAIL,
                note=("Caused by the net-change error above."
                      if change_finding["status"] == FAIL else ""),
            )

    # ── B. internal consistency ──────────────────────────────────────────────

    def check_cross_statement_consistency(self) -> None:
        for year in self.years:
            income_profit = self._get(self.income, "Profit for the year", year)
            cash_flow_profit = self._get(self.cash_flow, "Profit for the year", year)
            self._record(
                check_id="XS_PROFIT_TIE", category="B. Internal consistency",
                statement="Income Statement vs Cash Flow", period=year,
                rule="Profit for the year must match across both statements",
                expected=income_profit, found=cash_flow_profit,
                note="The cash flow statement should open with the exact "
                     "profit figure reported on the income statement.",
            )

            cash_component = None
            if not _missing(self._get(self.balance, "Cash and balances with RBI", year),
                            self._get(self.balance, "Balances with banks and money at call", year)):
                cash_component = (self._get(self.balance, "Cash and balances with RBI", year)
                                  + self._get(self.balance,
                                             "Balances with banks and money at call", year))
            closing_cash = self._get(self.cash_flow, "Closing cash and cash equivalents", year)
            self._record(
                check_id="XS_CASH_TIE", category="B. Internal consistency",
                statement="Balance Sheet vs Cash Flow", period=year,
                rule="Closing cash on the cash flow statement must equal cash "
                     "and bank balances on the balance sheet",
                expected=cash_component, found=closing_cash,
            )

    # ── C. prior year tie-out ────────────────────────────────────────────────

    def check_prior_year_tieout(self) -> None:
        """
        This year's comparative columns must match what was actually filed
        last year. Every current-year check can pass while this one still
        finds a silent restatement — which is exactly what happened to
        FY2024 deposits in the demo file.
        """
        if self.prior_year.empty:
            self._record(
                check_id="PY_NOT_SUPPLIED", category="C. Prior year tie-out",
                statement="Prior Year Published", period="-",
                rule="Comparatives must match the prior year's filed figures",
                expected=None, found=None,
                note="No prior-year reference was supplied with this upload. "
                     "This check was skipped, not passed.",
            )
            return

        lookup = {
            "Total income": self.income, "Profit for the year": self.income,
            "Total assets": self.balance, "Deposits": self.balance,
            "Advances": self.balance, "Reserves and surplus": self.balance,
            "Total equity": self.balance,
        }
        for row, source in lookup.items():
            for year in self.prior_year.columns:
                if year not in self.years:
                    continue
                filed = self._get(self.prior_year, row, year)
                current = self._get(source, row, year)
                self._record(
                    check_id=f"PY_{row.upper().replace(' ', '_')}",
                    category="C. Prior year tie-out",
                    statement=f"{row} vs prior filing", period=year,
                    rule=f"{row} as currently shown must match what was filed last year",
                    expected=filed, found=current,
                    note="A difference here means this figure was restated "
                         "without being disclosed as such." if filed != current else "",
                )

    # ── D. ratio verification ────────────────────────────────────────────────

    def check_ratios(self) -> None:
        """
        Recompute every published ratio from the statements and compare.
        Never reuse the published number as our own — the comparison is the
        product.
        """
        if self.ratios.empty:
            self._record(
                check_id="RATIO_NOT_SUPPLIED", category="D. Ratio verification",
                statement="Key Ratios", period="-",
                rule="Published ratios must match recomputed ratios",
                expected=None, found=None,
                note="No published ratio sheet was supplied. This check was "
                     "skipped, not passed.",
            )
            return

        for year in self.years:
            if year not in self.ratios.columns:
                continue
            g_income = lambda row: self._get(self.income, row, year)
            g_balance = lambda row: self._get(self.balance, row, year)
            g_published = lambda name: self._get(self.ratios, name, year)

            calculations = [
                ("RATIO_COST_INCOME", "Cost to income %",
                 "Total operating expenses / Total income x 100",
                 g_income("Total operating expenses"), g_income("Total income")),
                ("RATIO_ROA", "Return on assets %",
                 "Profit for the year / Total assets x 100",
                 g_income("Profit for the year"), g_balance("Total assets")),
                ("RATIO_ROE", "Return on equity %",
                 "Profit for the year / Total equity x 100",
                 g_income("Profit for the year"), g_balance("Total equity")),
                ("RATIO_CREDIT_COST", "Credit cost %",
                 "Provisions and contingencies / Advances x 100",
                 g_income("Provisions and contingencies"), g_balance("Advances")),
                ("RATIO_CREDIT_DEPOSIT", "Credit to deposit %",
                 "Advances / Deposits x 100",
                 g_balance("Advances"), g_balance("Deposits")),
            ]
            for check_id, ratio_name, formula, numerator, denominator in calculations:
                computed = (None if _missing(numerator, denominator) or not denominator
                            else round(numerator / denominator * 100, 2))
                published = g_published(ratio_name)
                delta = (None if _missing(computed, published)
                         else round(published - computed, 4))
                status = (INFO if delta is None else
                          PASS if abs(delta) <= RATIO_TOLERANCE_PP else FAIL)
                self.findings.append({
                    "check_id": check_id, "category": "D. Ratio verification",
                    "statement": "Key Ratios", "period": year,
                    "rule": f"{ratio_name} = {formula}",
                    "expected": computed, "found": published, "delta": delta,
                    "status": status, "root_cause": True,
                    "note": (f"We independently compute {computed}%; the "
                             f"published figure is {published}%."
                             if status == FAIL else ""),
                })

    # ── E. spelling and grammar ──────────────────────────────────────────────

    def check_labels(self) -> None:
        """Misspelled line-item labels, already found while reading the file."""
        for issue in self.data.get("label_issues", []):
            self.findings.append({
                "check_id": "SPELL_LABEL", "category": "E. Spelling and grammar",
                "statement": issue["sheet"], "period": "-",
                "rule": "Line-item labels must match the standard terminology",
                "expected": issue["suggestion"], "found": issue["found"],
                "delta": None, "status": INFO, "root_cause": True,
                "note": (f"'{issue['found']}' looks like a misspelling of "
                         f"'{issue['suggestion']}' "
                         f"({issue['similarity']:.0%} match)."),
            })

    def check_notes(self) -> None:
        """
        Spelling and grammar in the narrative disclosures.

        Deliberately small and explainable: a short list of common misspellings
        plus a few grammar patterns any of you can read in thirty seconds. Not
        a general-purpose language model — a general model would also be much
        harder to defend to a panel asking "how does this work?"
        """
        common_misspellings = {
            "recieved": "received", "seperate": "separate", "occured": "occurred",
            "acheive": "achieve", "wich": "which", "teh": "the",
            "managment": "management", "committment": "commitment",
        }
        grammar_patterns = [
            (r"\bThe Bank have\b", "The Bank has",
             "Subject-verb disagreement: 'Bank' is singular."),
            (r"\bThe Board have\b", "The Board has",
             "Subject-verb disagreement: 'Board' is singular."),
            (r"\bwas approved by the Board on\b.*\bwas approved by the Board on\b", None,
             "Repeated approval clause — possible duplicated sentence."),
        ]

        import re
        for note in self.notes:
            text, note_id = note["text"], note["note"]

            for wrong, right in common_misspellings.items():
                if re.search(rf"\b{wrong}\b", text, re.IGNORECASE):
                    self.findings.append({
                        "check_id": "SPELL_NOTE", "category": "E. Spelling and grammar",
                        "statement": "Notes", "period": note_id,
                        "rule": "Narrative text must be free of misspellings",
                        "expected": right, "found": wrong, "delta": None,
                        "status": INFO, "root_cause": True,
                        "note": f"'{wrong}' appears to be a misspelling of '{right}'.",
                    })

            for pattern, _, explanation in grammar_patterns:
                if re.search(pattern, text):
                    self.findings.append({
                        "check_id": "GRAMMAR_NOTE", "category": "E. Spelling and grammar",
                        "statement": "Notes", "period": note_id,
                        "rule": "Narrative text must be grammatically correct",
                        "expected": None, "found": text, "delta": None,
                        "status": INFO, "root_cause": True, "note": explanation,
                    })

    # ── run everything ───────────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        self.findings = []
        self.check_income_statement()
        self.check_balance_sheet()
        self.check_cash_flow()
        self.check_cross_statement_consistency()
        self.check_prior_year_tieout()
        self.check_ratios()
        self.check_labels()
        self.check_notes()

        summary = {status: 0 for status in (PASS, WARN, FAIL, INFO)}
        for finding in self.findings:
            summary[finding["status"]] += 1
        root_cause_failures = sum(1 for f in self.findings
                                  if f["status"] == FAIL and f["root_cause"])

        return {
            "company_name": self.data["company_name"],
            "source_file": self.data["source_file"],
            "source_format": self.data.get("source_format"),
            "tolerance_crore": self.tolerance,
            "periods_checked": self.years,
            "summary": {"total_checks": len(self.findings), **summary,
                       "root_cause_failures": root_cause_failures},
            "verdict": ("EXCEPTIONS FOUND" if summary[FAIL]
                       else "CLEAN (rounding differences noted)" if summary[WARN]
                       else "CLEAN"),
            "findings": self.findings,
        }


def review_file(paths) -> Dict[str, Any]:
    """Convenience: load and review in one call."""
    from backend.ingestion.loader import load_statements
    return StatementReviewEngine(load_statements(paths)).run()


# ── CLI ──────────────────────────────────────────────────────────────────────
#   python -m backend.review.engine data/review/MeridianBank_FY2026.xlsx
#   python -m backend.review.engine data/review/MeridianBank_FY2026.xlsx --all

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Review a fixed-schema statement set.")
    parser.add_argument("filepath")
    parser.add_argument("--all", action="store_true", help="show PASS rows too")
    parser.add_argument("--json", metavar="OUT")
    args = parser.parse_args()

    report = review_file(args.filepath)
    counts = report["summary"]

    print(f"\n{report['company_name']}  ({report['source_file']})")
    print(f"Verdict: {report['verdict']}")
    print(f"{counts['total_checks']} checks -> {counts['PASS']} pass, "
          f"{counts['WARN']} warn, {counts['FAIL']} fail, {counts['INFO']} info")
    print()

    shown = [f for f in report["findings"]
            if args.all or f["status"] in (FAIL, WARN, INFO)]
    for finding in shown:
        marker = "" if finding["root_cause"] else "  (knock-on)"
        print(f"[{finding['status']:<5}] {finding['period']:<8} "
              f"{finding['check_id']:<24} {finding['rule']}{marker}")
        if finding["status"] in (FAIL, WARN):
            print(f"          expected {finding['expected']}, found "
                  f"{finding['found']}, delta {finding['delta']:+,.2f}")
        if finding["note"]:
            print(f"          {finding['note']}")
        print()

    if args.json:
        import json
        with open(args.json, "w") as handle:
            json.dump(report, handle, indent=2)
        print(f"Wrote {args.json}")