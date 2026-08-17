# Financial Statement Reviewer & Planning Analytics Engine

Automated review of financial statements: mathematical accuracy, internal
consistency, prior-year tie-outs, ratio verification, and spelling and
grammar — producing a signable WP-514 audit workpaper.

**Every figure is computed in Python. The language model only writes
commentary about numbers that have already been verified.**

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt
python tools/make_dataset.py     # builds the demo dataset
python -m pytest tests/ -q       # 90 tests
```

Run the app in two terminals:

```bash
uvicorn backend.api.main:app --reload --port 8000    # terminal 1
streamlit run frontend/app.py                        # terminal 2
```

Open http://localhost:8501 for the app, or http://localhost:8000/docs for the
API browser.

Optional: copy `.env.example` to `.env` and add a Gemini key for AI
commentary. Without one the tool still runs end to end using engine-written
text — that is by design, not a fallback we hope never fires.

---

## What it checks

| Section | Checks |
|---|---|
| A. Mathematical accuracy | Do the subtotals add up, on every statement, every year |
| B. Internal consistency | Do the statements agree with each other |
| C. Prior year tie-out | Do this year's comparatives match what was filed last year |
| D. Ratio verification | Do published ratios match what we independently recompute |
| E. Spelling and grammar | Line-item labels and narrative disclosures |

Results carry four statuses. **WARN** exists because real statements contain
rounding, and a tool that shows a ₹1 crore gap in the same red as a ₹2,300
crore one is not trusted twice.

Where one bad cell breaks several checks, only the first is marked
`root_cause` — so a reviewer fixes one cell instead of chasing three.

---

## The dataset

`tools/make_dataset.py` generates two fictional banks. Every number is either
a typed base input or derived by the script, so the clean workbooks tie out
exactly.

| File | Purpose |
|---|---|
| `data/clean/MeridianBank_FY2026_CLEAN.xlsx` | Every check passes |
| `data/review/MeridianBank_FY2026.xlsx` | 13 planted defects — the demo file |
| `data/clean/SterlingBank_FY2026_CLEAN.xlsx` | The comparison peer |

`data/EXPECTED_FINDINGS.json` is the answer key: every cell changed, its
original value, and which checks should fire. That is what lets the test
suite prove all 13 defects are caught rather than just asserting the code
returns whatever the code returns.

CSV equivalents of every sheet live beside each workbook. Upload one workbook
or several CSVs — the reader identifies each file by its contents, not its
name.

See `data/DATASET_GUIDE.md` for a plain-English dictionary of every line item.

---

## Layout

```
backend/
├── ingestion/          reading files into one canonical shape
│   ├── statements.py     the shape + expected vocabulary + fuzzy matching
│   ├── loader.py         the front door: load_statements()
│   └── readers/          one module per input format
├── review/
│   ├── engine.py         all the checks
│   ├── peer.py           benchmarking two companies
│   ├── narrative.py      AI commentary on the findings
│   └── wp514.py          the Excel workpaper
├── llm.py              the only place we talk to a model
└── api/main.py         FastAPI server
frontend/               Streamlit app
tools/make_dataset.py   generates the demo data
tests/                  90 tests
```

Adding a new input format means writing one reader and adding one line to
`loader.py`. Nothing downstream changes, because nothing downstream ever
touches a file.
