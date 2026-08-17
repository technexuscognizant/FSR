# Dataset Guide — Meridian Commercial Bank Limited

Synthetic financial statements for a fictional Indian scheduled commercial bank.
All figures in **INR crore**. Three years: FY2024, FY2025, FY2026.

Built by `tools/make_dataset.py`. **Never edit these files by hand** — change the
script and regenerate, or the answer key stops matching the data.

## Two files, and why both exist

| File | Purpose |
|---|---|
| `data/clean/MeridianBank_FY2026_CLEAN.xlsx` | Every check passes. Proves the tool stays quiet on good data. |
| `data/review/MeridianBank_FY2026.xlsx` | 13 planted defects. Proves the tool finds bad data. |

You need both. A validator tested only on broken files can't be shown to avoid
false alarms; one tested only on clean files can't be shown to catch anything.

CSV versions of every sheet sit in `csv/` beside each workbook, one file per
sheet, identical content.

---

## Sheet layout

Every statement sheet uses the same shape:

```
Particular | FY2024 | FY2025 | FY2026
```

Column A is the line-item name, columns B–D are the years. No merged cells,
no blank spacer rows, no trailing scenario columns. This is what makes the
reader simple: find the row by name, read across.

---

## Income_Statement — what the bank earned

A bank's income statement differs from a normal company's. It doesn't sell
products; it lends money and charges for services.

| Line item | Plain English | Formula |
|---|---|---|
| Interest income | Interest earned from borrowers | input |
| Interest expense | Interest paid to depositors and lenders | input |
| **Net interest income** | The core spread the bank earns | Interest income − Interest expense |
| Fee and commission income | Charges for cards, transfers, services | input |
| Treasury and other income | Gains from investments and trading | input |
| **Total other income** | All non-interest earnings | Fee + Treasury |
| **Total income** | Everything the bank earned | NII + Total other income |
| Employee cost | Salaries | input |
| Depreciation and amortisation | Wearing out of buildings, systems | input |
| Other operating expenses | Rent, technology, everything else | input |
| **Total operating expenses** | Cost of running the bank | Employee + Depreciation + Other |
| **Operating profit before provisions** | Profit before bad-loan losses | Total income − Total opex |
| Provisions and contingencies | Money set aside for loans that may not be repaid | input |
| **Profit before tax** | | Operating profit − Provisions |
| Tax expense | | input |
| **Profit for the year** | The bottom line | PBT − Tax |
| **Basic earnings per share** | Profit per share | Profit ÷ shares |

## Balance_Sheet — what the bank owns and owes

The one rule that must never break: **Total assets = Total liabilities + Total equity.**

| Line item | Plain English |
|---|---|
| Cash and balances with RBI | Cash, plus the reserve the central bank requires |
| Balances with banks and money at call | Money held at other banks, withdrawable quickly |
| Investments | Government and corporate bonds the bank holds |
| Advances | Loans given to customers. A bank's biggest asset |
| Fixed assets | Branches, computers |
| Other assets | Everything else |
| **Total assets** | Sum of the six above |
| Deposits | Customer money. A bank's biggest **liability** — it owes this back |
| Borrowings | Money the bank itself borrowed |
| Other liabilities and provisions | Everything else owed |
| **Total liabilities** | Sum of the three above |
| Share capital | Money from shareholders |
| Reserves and surplus | Accumulated past profits not paid out |
| **Total equity** | Share capital + Reserves |

The one that confuses everyone: **deposits are a liability, loans are an asset.**
Your money in a bank is money the bank owes you.

## Cash_Flow — where cash actually moved

Profit and cash are different things. This sheet tracks cash.

Three sections — operating, investing, financing — each with a subtotal, then:

```
Net increase = Operating + Investing + Financing
Closing cash = Opening cash + Net increase
```

And `Closing cash` must equal `Cash and balances with RBI + Balances with banks`
on the balance sheet. That cross-sheet tie is one of the strongest checks in the tool.

## Key_Ratios — the planning analytics

Ten ratios, each with a **Basis** column stating its formula in words. That
column exists so the ratio check is unambiguous: we recompute using exactly
the stated formula and compare.

| Ratio | What it tells you |
|---|---|
| Net interest margin % | How profitably the bank lends |
| Cost to income % | Efficiency. Lower is better |
| Return on assets % | Profit per rupee of assets |
| Return on equity % | Profit per rupee of shareholder money |
| Credit cost % | How much lending is going bad |
| Credit to deposit % | How much of deposits is lent out |
| Growth % rows | Year-on-year change |

## Prior_Year_Published — last year's filed figures

FY2024 and FY2025 **as published in the previous annual report**.

The current statements repeat those years as comparatives. Those comparatives
must match what was already filed. When they don't, something was restated —
and a restatement nobody disclosed is exactly what an auditor hunts for.

This is the **prior year tie-out** the brief asks for. It cannot be checked from
one year's statements alone, which is why this sheet exists.

## Notes — narrative text

Six short disclosure sentences. This is what the spelling and grammar module
reads. Numbers alone can't demonstrate that requirement.

---

## The 13 planted defects

Full detail with before/after values in `data/EXPECTED_FINDINGS.json`.

| ID | Type | Where | What's wrong |
|---|---|---|---|
| D01 | Math | Income_Statement FY2026 | Total opex understated by 100 |
| D02 | Math | Balance_Sheet FY2026 | Total assets overstated by 2,300 — **doesn't balance** |
| D03 | Math | Balance_Sheet FY2025 | Reserves understated by 2,700 |
| D04 | Math | Cash_Flow FY2026 | Closing cash out by 15 |
| D05 | Consistency | Cash_Flow FY2025 | Profit differs from Income_Statement by 54 |
| D06 | **Rounding** | Cash_Flow FY2024 | Out by **1** — must be WARN, not FAIL |
| D07 | Prior year | Prior_Year_Published FY2024 | Deposits differ from filed figure by 1,400 |
| D08 | Ratio | Key_Ratios FY2025 | Published ROE overstated by 2.15pp |
| D09 | Spelling | Income_Statement | "Provisons and contingencies" |
| D10 | Spelling | Balance_Sheet | "Reserves and surpluss" |
| D11 | Spelling | Cash_Flow | "Dividends payed" |
| D12 | Grammar | Notes N2 | "The Bank **have** adopted" |
| D13 | Spelling | Notes N4 | "The Board **recieved**" |

### Four of these are doing specific work

**D06 is one crore.** Real statements are full of rounding. A tool that shows
₹1 crore in the same red as ₹2,300 crore is not trusted twice. This forces a
severity tier.

**D01 cascades three ways** — the opex subtotal fails, operating profit fails
because it's built on opex, and the published cost-to-income ratio disagrees
because it was computed from the correct figure. One typo, three findings.
Your UI should mark the first as the root cause and fold the others under it,
or a reviewer chases three cells when there's one.

**D03 is caught twice, by different routes** — the equity subtotal fails, and
independently the prior-year tie-out fails. Two unrelated checks converging on
one cell is a strong demonstration.

**D07 is invisible to every current-year check.** Every FY2024 number is
internally consistent. Only comparing against what was filed last year finds
it. This is the defect that justifies the whole prior-year module.

**D10 sits on a row that is also numerically wrong.** The reader has to still
find "Reserves and surpluss" despite the typo. Fuzzy label matching isn't
optional — it's load-bearing.

---

## Regenerating

```bash
python tools/make_dataset.py
```

Deterministic — same output every time. To add a defect, add an entry to the
`DEFECTS` list in the script; the answer key updates itself.