"""
tools/make_dataset.py
=====================
Builds the project's demo dataset from scratch, reproducibly.

    python tools/make_dataset.py

WHY A SCRIPT AND NOT A HAND-MADE FILE
-------------------------------------
Every number below is either typed once as a base input, or DERIVED by this
script from those inputs. That means the clean workbook is guaranteed to tie
out perfectly — we never have to hunt a stray rupee by hand.

It also means the corrupted workbook has a written answer key. We know
exactly which cell we broke, what it used to be, and which checks should
fire. Without that, "our validator found 14 problems" is unprovable — you
cannot show it found ALL of them, or that it stays quiet on a clean file.

WHAT IT PRODUCES
    data/clean/MeridianBank_FY2026_CLEAN.xlsx     every check must pass
    data/review/MeridianBank_FY2026.xlsx          the demo file, 12 defects
    data/clean/csv/*.csv                          same data, one file per sheet
    data/review/csv/*.csv
    data/EXPECTED_FINDINGS.json                   the answer key

THE COMPANY
    Meridian Commercial Bank Limited, a fictional Indian scheduled commercial
    bank. Figures in INR crore. Banking was chosen because the problem
    statement names Banking as the domain.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

YEARS = ["FY2024", "FY2025", "FY2026"]
UNIT = "INR Crore"
COMPANY = "Meridian Commercial Bank Limited"

# Two banks so peer comparison has something real to compare. Sterling is
# deliberately the smaller, faster-growing, less efficient one — a bank that
# is winning share while spending more to do it. That contrast is what makes
# a benchmarking page worth looking at; two near-identical banks would show
# nothing.
PEER = "Sterling Capital Bank Limited"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")


# ═══════════════════════════════════════════════════════════════════════════
# BASE INPUTS — the only numbers typed by hand. Everything else is derived.
# ═══════════════════════════════════════════════════════════════════════════

BASE_MERIDIAN = {
    # income statement
    "interest_income":        [48200, 54700, 61350],
    "interest_expense":       [27450, 31600, 35880],
    "fee_income":             [5420, 6180, 7010],
    "treasury_income":        [1860, 2040, 2395],
    "employee_cost":          [6340, 7120, 7880],
    "depreciation":           [620, 680, 745],
    "other_opex":             [5180, 5760, 6410],
    "provisions":             [4210, 4050, 3780],
    "tax":                    [2940, 3450, 4040],
    "shares_basic":           [640, 645, 650],
    "shares_diluted":         [646, 651, 657],

    # balance sheet — assets
    "cash_with_rbi":          [24300, 26850, 28400],
    "balances_with_banks":    [9150, 10420, 11980],
    "advances":               [392400, 441700, 498250],
    "fixed_assets":           [4820, 5150, 5540],
    "other_assets":           [18730, 20580, 22930],

    # balance sheet — liabilities
    "deposits":               [468900, 526400, 592300],
    "borrowings":             [62100, 68900, 75400],
    "other_liabilities":      [21400, 23700, 26100],

    # equity
    "share_capital":          [1280, 1290, 1300],
    "opening_reserves_fy24":  44320,
    "dividends_paid":         [2580, 2580, 3010],

    # cash flow
    "working_capital_change": [-1170, -110, -295],
    "fixed_asset_purchase":   [-880, -1010, -1135],
    "net_securities":         [-5420, -6410, -7765],
    "share_issue_proceeds":   [150, 160, 170],
    "borrowing_repayment":    [-320, -1220, -1400],
    "opening_cash_fy24":      30100,
}



# Sterling: about 55% of Meridian's size, growing faster, but paying more to
# do it — higher employee and other costs, thinner margins, more provisions.
BASE_STERLING = {
    "interest_income":        [26400, 31900, 38200],
    "interest_expense":       [15850, 19400, 23500],
    "fee_income":             [3180, 3910, 4780],
    "treasury_income":        [1040, 1180, 1420],
    "employee_cost":          [4120, 4980, 5960],
    "depreciation":           [410, 470, 545],
    "other_opex":             [3380, 4010, 4830],
    "provisions":             [2980, 3140, 3260],
    "tax":                    [1120, 1330, 1610],
    "shares_basic":           [410, 418, 425],
    "shares_diluted":         [415, 424, 432],

    "cash_with_rbi":          [13200, 15400, 17600],
    "balances_with_banks":    [5100, 6250, 7480],
    "advances":               [214000, 258000, 309000],
    "fixed_assets":           [2740, 3080, 3460],
    "other_assets":           [10600, 12400, 14500],

    "deposits":               [252000, 300000, 356000],
    "borrowings":             [38400, 45200, 53100],
    "other_liabilities":      [11900, 13800, 15900],

    "share_capital":          [820, 836, 850],
    "opening_reserves_fy24":  22600,
    "dividends_paid":         [860, 940, 1080],

    "working_capital_change": [-780, -640, -520],
    "fixed_asset_purchase":   [-640, -730, -840],
    "net_securities":         [-3180, -3960, -4820],
    "share_issue_proceeds":   [110, 120, 130],
    "borrowing_repayment":    [-240, -310, -380],
    "opening_cash_fy24":      16800,
}

PROFILES = {
    "MeridianBank": (COMPANY, BASE_MERIDIAN),
    "SterlingBank": (PEER, BASE_STERLING),
}


def build_numbers(base: Dict[str, Any] = None) -> Dict[str, List[float]]:
    """Derive every computed line so the clean workbook ties out exactly."""
    base = base if base is not None else BASE_MERIDIAN
    n: Dict[str, List[Any]] = {k: list(v) if isinstance(v, list) else v
                               for k, v in base.items()}

    n["nii"] = [a - b for a, b in zip(n["interest_income"], n["interest_expense"])]
    n["other_income"] = [a + b for a, b in zip(n["fee_income"], n["treasury_income"])]
    n["total_income"] = [a + b for a, b in zip(n["nii"], n["other_income"])]
    n["total_opex"] = [a + b + c for a, b, c in
                       zip(n["employee_cost"], n["depreciation"], n["other_opex"])]
    n["operating_profit"] = [a - b for a, b in zip(n["total_income"], n["total_opex"])]
    n["pbt"] = [a - b for a, b in zip(n["operating_profit"], n["provisions"])]
    n["pat"] = [a - b for a, b in zip(n["pbt"], n["tax"])]
    n["eps_basic"] = [round(p / s, 2) for p, s in zip(n["pat"], n["shares_basic"])]
    n["eps_diluted"] = [round(p / s, 2) for p, s in zip(n["pat"], n["shares_diluted"])]

    # Reserves roll forward: opening + profit - dividend. This is what makes
    # the prior-year tie-out a real check rather than a decorative one.
    reserves = [n["opening_reserves_fy24"]]
    for index in (1, 2):
        reserves.append(reserves[-1] + n["pat"][index] - n["dividends_paid"][index])
    n["reserves"] = reserves
    n["total_equity"] = [a + b for a, b in zip(n["share_capital"], n["reserves"])]
    n["total_liabilities"] = [a + b + c for a, b, c in
                              zip(n["deposits"], n["borrowings"], n["other_liabilities"])]

    # Investments is the balancing asset, so total assets = liabilities + equity
    # exactly. A real bank's investment book absorbs surplus funding, so this
    # is a realistic place to balance rather than a fudge line.
    n["total_assets"] = [a + b for a, b in zip(n["total_liabilities"], n["total_equity"])]
    n["investments"] = [
        total - (cash + banks + adv + fixed + other)
        for total, cash, banks, adv, fixed, other in zip(
            n["total_assets"], n["cash_with_rbi"], n["balances_with_banks"],
            n["advances"], n["fixed_assets"], n["other_assets"])
    ]

    # cash flow
    n["cash_equivalents"] = [a + b for a, b in
                             zip(n["cash_with_rbi"], n["balances_with_banks"])]
    n["cf_operating"] = [pat + dep + prov + wc for pat, dep, prov, wc in
                         zip(n["pat"], n["depreciation"], n["provisions"],
                             n["working_capital_change"])]
    n["cf_investing"] = [a + b for a, b in
                         zip(n["fixed_asset_purchase"], n["net_securities"])]
    n["cf_financing"] = [a + b + c for a, b, c in
                         zip(n["share_issue_proceeds"], n["borrowing_repayment"],
                             [-d for d in n["dividends_paid"]])]

    # Opening cash for FY2024 is an input; after that it is the prior close.
    n["opening_cash"] = [n["opening_cash_fy24"],
                         n["cash_equivalents"][0], n["cash_equivalents"][1]]
    n["net_cash_change"] = [c - o for c, o in
                            zip(n["cash_equivalents"], n["opening_cash"])]

    # Operating cash is solved BACKWARDS for every year, so the statement
    # always closes on the cash balance the balance sheet already reports.
    #
    # Doing this for FY2024 only (as an earlier version did) left FY2025 and
    # FY2026 depending on the typed working-capital figures happening to
    # reconcile. That held for the first company by luck and broke the moment
    # a second one was added. Solving every year removes the hidden
    # constraint: any new company profile now ties out automatically.
    for index in range(len(YEARS)):
        n["cf_operating"][index] = (n["net_cash_change"][index]
                                    - n["cf_investing"][index]
                                    - n["cf_financing"][index])
        n["working_capital_change"][index] = (
            n["cf_operating"][index] - n["pat"][index]
            - n["depreciation"][index] - n["provisions"][index])
    return n


# ═══════════════════════════════════════════════════════════════════════════
# SHEET LAYOUTS — uniform [Particular, FY2024, FY2025, FY2026] geometry
# ═══════════════════════════════════════════════════════════════════════════

def sheets(n: Dict[str, List[float]]) -> Dict[str, pd.DataFrame]:
    def frame(rows: List[tuple]) -> pd.DataFrame:
        # Cast whole numbers back to int. EPS is fractional, and a single
        # float in a column makes pandas render every value as 48200.00,
        # which looks wrong in both Excel and CSV.
        def tidy(value):
            return int(value) if float(value).is_integer() else value

        # dtype=object is essential: without it pandas upcasts the whole
        # column to float64 because EPS is fractional, undoing the int cast
        # above and writing 48200.0 into every cell.
        return pd.DataFrame(
            [[label] + [tidy(v) for v in values] for label, values in rows],
            columns=["Particular"] + YEARS, dtype=object,
        )

    income = frame([
        ("Interest income", n["interest_income"]),
        ("Interest expense", n["interest_expense"]),
        ("Net interest income", n["nii"]),
        ("Fee and commission income", n["fee_income"]),
        ("Treasury and other income", n["treasury_income"]),
        ("Total other income", n["other_income"]),
        ("Total income", n["total_income"]),
        ("Employee cost", n["employee_cost"]),
        ("Depreciation and amortisation", n["depreciation"]),
        ("Other operating expenses", n["other_opex"]),
        ("Total operating expenses", n["total_opex"]),
        ("Operating profit before provisions", n["operating_profit"]),
        ("Provisions and contingencies", n["provisions"]),
        ("Profit before tax", n["pbt"]),
        ("Tax expense", n["tax"]),
        ("Profit for the year", n["pat"]),
        ("Number of equity shares (crore)", n["shares_basic"]),
        ("Diluted equity shares (crore)", n["shares_diluted"]),
        ("Basic earnings per share", n["eps_basic"]),
        ("Diluted earnings per share", n["eps_diluted"]),
    ])

    balance = frame([
        ("Cash and balances with RBI", n["cash_with_rbi"]),
        ("Balances with banks and money at call", n["balances_with_banks"]),
        ("Investments", n["investments"]),
        ("Advances", n["advances"]),
        ("Fixed assets", n["fixed_assets"]),
        ("Other assets", n["other_assets"]),
        ("Total assets", n["total_assets"]),
        ("Deposits", n["deposits"]),
        ("Borrowings", n["borrowings"]),
        ("Other liabilities and provisions", n["other_liabilities"]),
        ("Total liabilities", n["total_liabilities"]),
        ("Share capital", n["share_capital"]),
        ("Reserves and surplus", n["reserves"]),
        ("Total equity", n["total_equity"]),
        ("Total liabilities and equity", [a + b for a, b in
                                          zip(n["total_liabilities"], n["total_equity"])]),
    ])

    cash = frame([
        ("Profit for the year", n["pat"]),
        ("Depreciation and amortisation", n["depreciation"]),
        ("Provisions and contingencies", n["provisions"]),
        ("Changes in working capital and other items", n["working_capital_change"]),
        ("Net cash from operating activities", n["cf_operating"]),
        ("Purchase of fixed assets", n["fixed_asset_purchase"]),
        ("Net investment in securities", n["net_securities"]),
        ("Net cash from investing activities", n["cf_investing"]),
        ("Proceeds from issue of share capital", n["share_issue_proceeds"]),
        ("Repayment of borrowings", n["borrowing_repayment"]),
        ("Dividends paid", [-d for d in n["dividends_paid"]]),
        ("Net cash from financing activities", n["cf_financing"]),
        ("Net increase in cash and cash equivalents", n["net_cash_change"]),
        ("Opening cash and cash equivalents", n["opening_cash"]),
        ("Closing cash and cash equivalents", n["cash_equivalents"]),
    ])

    # Planning analytics. The Basis column states the formula in words, so the
    # ratio check is unambiguous and a reader can see what we recomputed.
    def pct(a, b):
        return [round(x / y * 100, 2) for x, y in zip(a, b)]

    def growth(series):
        return ["-"] + [round((series[i] - series[i - 1]) / series[i - 1] * 100, 2)
                        for i in (1, 2)]

    ratios = pd.DataFrame([
        ["Net interest margin %", *pct(n["nii"], [a + b for a, b in
                                                  zip(n["advances"], n["investments"])]),
         "Net interest income / (Advances + Investments) x 100"],
        ["Cost to income %", *pct(n["total_opex"], n["total_income"]),
         "Total operating expenses / Total income x 100"],
        ["Return on assets %", *pct(n["pat"], n["total_assets"]),
         "Profit for the year / Total assets x 100"],
        ["Return on equity %", *pct(n["pat"], n["total_equity"]),
         "Profit for the year / Total equity x 100"],
        ["Credit cost %", *pct(n["provisions"], n["advances"]),
         "Provisions and contingencies / Advances x 100"],
        ["Credit to deposit %", *pct(n["advances"], n["deposits"]),
         "Advances / Deposits x 100"],
        ["Total income growth %", *growth(n["total_income"]),
         "Year on year change in Total income"],
        ["Profit growth %", *growth(n["pat"]),
         "Year on year change in Profit for the year"],
        ["Advances growth %", *growth(n["advances"]),
         "Year on year change in Advances"],
        ["Deposits growth %", *growth(n["deposits"]),
         "Year on year change in Deposits"],
    ], columns=["Metric"] + YEARS + ["Basis"], dtype=object)

    # As published in last year's annual report. The current statements repeat
    # FY2024 and FY2025 as comparatives; those must agree with what was
    # already filed. This is the "prior year tie out" the brief asks for, and
    # it cannot be checked from a single year's statements alone.
    prior = pd.DataFrame([
        ["Total income", n["total_income"][0], n["total_income"][1]],
        ["Profit for the year", n["pat"][0], n["pat"][1]],
        ["Total assets", n["total_assets"][0], n["total_assets"][1]],
        ["Deposits", n["deposits"][0], n["deposits"][1]],
        ["Advances", n["advances"][0], n["advances"][1]],
        ["Reserves and surplus", n["reserves"][0], n["reserves"][1]],
        ["Total equity", n["total_equity"][0], n["total_equity"][1]],
    ], columns=["Particular", "FY2024", "FY2025"], dtype=object)

    notes = pd.DataFrame([
        ["N1", "The financial statements have been prepared on a going concern "
               "basis under the historical cost convention."],
        ["N2", "The Bank has adopted the revised accounting standards notified "
               "during the year ended 31 March 2026."],
        ["N3", "Provisions were made in accordance with the prudential norms "
               "issued by the regulator."],
        ["N4", "The Board received the report of the Audit Committee on "
               "12 May 2026."],
        ["N5", "Advances are stated net of provisions held against "
               "non-performing assets."],
        ["N6", "There were no material events after the reporting date "
               "requiring adjustment or disclosure."],
    ], columns=["Note", "Text"])

    return {
        "Income_Statement": income,
        "Balance_Sheet": balance,
        "Cash_Flow": cash,
        "Key_Ratios": ratios,
        "Prior_Year_Published": prior,
        "Notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# THE DEFECTS — every one deliberate, recorded, and independently reasoned
# ═══════════════════════════════════════════════════════════════════════════
# kind: math | consistency | prior_year | ratio | spelling | grammar
# severity: FAIL for a real error, WARN for a rounding difference

DEFECTS: List[Dict[str, Any]] = [
    {
        "id": "D01", "kind": "math", "severity": "FAIL",
        "sheet": "Income_Statement", "row": "Total operating expenses",
        "year": "FY2026", "delta": -100,
        "story": "Subtotal understated. Employee cost + depreciation + other "
                 "opex no longer equals the printed total.",
        # Note: this also nudges the published cost-to-income ratio (delta
        # ~0.29pp), but that is below the ratio tolerance and correctly stays
        # PASS — a 100 Cr shift on a ~35,000 Cr income base is not a material
        # ratio movement. Only the two checks below are expected to FAIL.
        "expected_checks": ["IS_TOTAL_OPEX", "IS_OPERATING_PROFIT"],
    },
    {
        "id": "D02", "kind": "math", "severity": "FAIL",
        "sheet": "Balance_Sheet", "row": "Total assets",
        "year": "FY2026", "delta": 2300,
        "story": "The classic. Total assets no longer equals liabilities plus "
                 "equity, and no longer equals the sum of its own components.",
        "expected_checks": ["BS_ASSET_COMPONENTS", "BS_BALANCE"],
    },
    {
        "id": "D03", "kind": "math", "severity": "FAIL",
        "sheet": "Balance_Sheet", "row": "Reserves and surplus",
        "year": "FY2025", "delta": -2700,
        "story": "Equity restated downwards. Breaks the equity subtotal and, "
                 "separately, disagrees with what was filed last year.",
        "expected_checks": ["BS_EQUITY_COMPONENTS", "PY_RESERVES_AND_SURPLUS"],
    },
    {
        "id": "D04", "kind": "math", "severity": "FAIL",
        "sheet": "Cash_Flow", "row": "Closing cash and cash equivalents",
        "year": "FY2026", "delta": 15,
        "story": "Closing balance does not equal opening plus the net movement, "
                 "and no longer agrees with cash on the balance sheet.",
        "expected_checks": ["CF_CLOSING_ROLLFORWARD", "XS_CASH_TIE"],
    },
    {
        "id": "D05", "kind": "consistency", "severity": "FAIL",
        "sheet": "Cash_Flow", "row": "Profit for the year",
        "year": "FY2025", "delta": -54,
        "story": "Digit transposition. The cash flow opens with a different "
                 "profit figure than the income statement reports.",
        "expected_checks": ["XS_PROFIT_TIE", "CF_OPERATING_SUBTOTAL"],
    },
    {
        "id": "D06", "kind": "math", "severity": "WARN",
        "sheet": "Cash_Flow", "row": "Net increase in cash and cash equivalents",
        "year": "FY2024", "delta": 1,
        "story": "One crore out. This is rounding, not an error, and must come "
                 "back as a warning. A tool that shows this in red beside a "
                 "2,300 crore failure is not trusted twice.",
        # Cascade: closing = opening + net change, so the roll-forward is
        # out by the same 1 crore. Both must be WARN, not FAIL.
        "expected_checks": ["CF_NET_CHANGE", "CF_CLOSING_ROLLFORWARD"],
    },
    {
        "id": "D07", "kind": "prior_year", "severity": "FAIL",
        "sheet": "Prior_Year_Published", "row": "Deposits",
        "year": "FY2024", "delta": -1400,
        "story": "The FY2024 deposits comparative in the current statements "
                 "does not match the figure already filed. Only a prior-year "
                 "tie-out finds this; every current-year check passes.",
        "expected_checks": ["PY_DEPOSITS"],
    },
    {
        "id": "D08", "kind": "ratio", "severity": "FAIL",
        "sheet": "Key_Ratios", "row": "Return on equity %",
        "year": "FY2025", "delta": 2.15,
        "story": "Published ratio overstated. Recomputing it from the "
                 "statements exposes the difference.",
        "expected_checks": ["RATIO_ROE"],
    },
    {
        "id": "D09", "kind": "spelling", "severity": "FAIL",
        "sheet": "Income_Statement", "row": "Provisions and contingencies",
        "typo": "Provisons and contingencies",
        "story": "Missing letter in a line-item label.",
        "expected_checks": ["SPELL_LABEL"],
    },
    {
        "id": "D10", "kind": "spelling", "severity": "FAIL",
        "sheet": "Balance_Sheet", "row": "Reserves and surplus",
        "typo": "Reserves and surpluss",
        "story": "Doubled letter. Note this row is also numerically wrong "
                 "(D03) — the reader must still find it despite the typo.",
        "expected_checks": ["SPELL_LABEL"],
    },
    {
        "id": "D11", "kind": "spelling", "severity": "FAIL",
        "sheet": "Cash_Flow", "row": "Dividends paid",
        "typo": "Dividends payed",
        "story": "Wrong past tense.",
        "expected_checks": ["SPELL_LABEL"],
    },
    {
        "id": "D12", "kind": "grammar", "severity": "FAIL",
        "sheet": "Notes", "row": "N2",
        "replacement": "The Bank have adopted the revised accounting standards "
                       "notified during the year ended 31 March 2026.",
        "story": "Subject-verb disagreement: 'The Bank have adopted'.",
        "expected_checks": ["GRAMMAR_NOTE"],
    },
    {
        "id": "D13", "kind": "grammar", "severity": "FAIL",
        "sheet": "Notes", "row": "N4",
        "replacement": "The Board recieved the report of the Audit Committee "
                       "on 12 May 2026.",
        "story": "Misspelling inside narrative text: 'recieved'.",
        "expected_checks": ["SPELL_NOTE"],
    },
]


def apply_defects(clean: Dict[str, pd.DataFrame]) -> tuple:
    """Return (corrupted sheets, answer key)."""
    broken = {name: frame.copy() for name, frame in clean.items()}
    manifest = []

    for defect in DEFECTS:
        sheet = broken[defect["sheet"]]
        record = {k: defect[k] for k in
                  ("id", "kind", "severity", "sheet", "row", "story",
                   "expected_checks")}

        if defect["kind"] in ("math", "consistency", "ratio", "prior_year"):
            label_column = "Metric" if defect["sheet"] == "Key_Ratios" else "Particular"
            mask = sheet[label_column] == defect["row"]
            year = defect["year"]
            before = float(sheet.loc[mask, year].iloc[0])
            after = round(before + defect["delta"], 2)
            sheet.loc[mask, year] = after
            record.update({"year": year, "clean_value": before,
                           "corrupted_value": after, "delta": defect["delta"]})

        elif defect["kind"] == "spelling":
            label_column = "Particular"
            mask = sheet[label_column] == defect["row"]
            sheet.loc[mask, label_column] = defect["typo"]
            record.update({"clean_value": defect["row"],
                           "corrupted_value": defect["typo"]})

        elif defect["kind"] == "grammar":
            mask = sheet["Note"] == defect["row"]
            record["clean_value"] = sheet.loc[mask, "Text"].iloc[0]
            sheet.loc[mask, "Text"] = defect["replacement"]
            record["corrupted_value"] = defect["replacement"]

        manifest.append(record)

    return broken, manifest


# ═══════════════════════════════════════════════════════════════════════════
# WRITE
# ═══════════════════════════════════════════════════════════════════════════

def write(sheets_map: Dict[str, pd.DataFrame], xlsx_path: str,
          csv_directory: str) -> None:
    os.makedirs(os.path.dirname(xlsx_path), exist_ok=True)
    os.makedirs(csv_directory, exist_ok=True)

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for name, frame in sheets_map.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            worksheet = writer.sheets[name]
            worksheet.column_dimensions["A"].width = 44
            for column in "BCDE":
                worksheet.column_dimensions[column].width = 15
            if name == "Notes":
                worksheet.column_dimensions["B"].width = 95
            if name == "Key_Ratios":
                worksheet.column_dimensions["E"].width = 52

    for name, frame in sheets_map.items():
        frame.to_csv(os.path.join(csv_directory, f"{name}.csv"), index=False)


def main() -> None:
    """
    Build every file for both companies.

    Meridian gets the 13 planted defects — it is the review demo. Sterling is
    generated clean only, because its job is to be the comparison peer, and a
    peer riddled with errors would muddy that story.
    """
    all_defects = []

    for slug, (company, base) in PROFILES.items():
        numbers = build_numbers(base)
        clean = sheets(numbers)

        write(clean, os.path.join(DATA, "clean", f"{slug}_FY2026_CLEAN.xlsx"),
              os.path.join(DATA, "clean", "csv", slug))

        if slug == "MeridianBank":
            broken, manifest = apply_defects(clean)
            write(broken, os.path.join(DATA, "review", f"{slug}_FY2026.xlsx"),
                  os.path.join(DATA, "review", "csv"))
            all_defects = manifest

        print(f"\n{company}")
        for name, frame in clean.items():
            print(f"  {name:<24} {frame.shape[0]:>3} rows")

    answer_key = {
        "companies": {slug: name for slug, (name, _) in PROFILES.items()},
        "unit": UNIT,
        "years": YEARS,
        "tolerance_crore": 1,
        "clean_files": [f"data/clean/{slug}_FY2026_CLEAN.xlsx" for slug in PROFILES],
        "review_file": "data/review/MeridianBank_FY2026.xlsx",
        "note": "Generated by tools/make_dataset.py. Do not edit by hand — "
                "regenerate instead, or the answer key stops matching.",
        "defect_count": len(all_defects),
        "defects": all_defects,
    }
    with open(os.path.join(DATA, "EXPECTED_FINDINGS.json"), "w") as handle:
        json.dump(answer_key, handle, indent=2, default=str)

    print(f"\n  {len(all_defects)} defects planted in the Meridian review file:")
    for record in all_defects:
        location = f"{record['sheet']}/{record.get('year', '')}"
        print(f"    {record['id']}  {record['severity']:<5} {record['kind']:<12} "
              f"{location:<28} {record['row']}")
    print(f"\n  Wrote data/clean/, data/review/ and data/EXPECTED_FINDINGS.json\n")


if __name__ == "__main__":
    main()