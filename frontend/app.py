"""
frontend/app.py
===============
Page 1 — Upload & Review.

Run it (backend must already be running):
    uvicorn backend.api.main:app --reload --port 8000     # terminal 1
    streamlit run frontend/app.py                         # terminal 2
"""

import sys
from pathlib import Path

# Streamlit runs this file as a standalone script, so the project root is not
# on the import path. This must come before any "from frontend..." import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from frontend.statements_client import ApiError, statements_api
from frontend import ui

ui.page_setup("Upload & Review", "🏦")
ui.page_header(
    "Financial Statement Reviewer",
    "Upload a statement workbook or CSV set. Every figure is verified in "
    "Python before any commentary is written.",
)

if not statements_api.is_up():
    st.error("Backend is not running. Start it in another terminal:\n\n"
             "```\nuvicorn backend.api.main:app --reload --port 8000\n```")
    st.stop()

ui.sidebar_status()

# ── upload ───────────────────────────────────────────────────────────────────
tab_xlsx, tab_csv = st.tabs(["📘 Excel workbook", "📄 CSV file set"])

with tab_xlsx:
    workbook = st.file_uploader("Statement workbook", type=["xlsx", "xlsm"],
                                key="wb")
    if workbook is not None and st.button("Load workbook", type="primary"):
        with st.spinner("Reading sheets…"):
            try:
                result = statements_api.upload([(workbook.name, workbook.getvalue())])
            except ApiError as error:
                st.error(str(error))
                st.stop()
        ui.remember_session(result)
        st.success(f"Loaded **{result['company_name']}** — "
                   f"{len(result['years'])} years, "
                   f"{result['label_issues_found']} label issue(s).")
        st.rerun()

with tab_csv:
    st.caption("One CSV per statement. Income Statement, Balance Sheet and "
               "Cash Flow are required; Key Ratios, Prior Year Published and "
               "Notes are optional — skipped checks say so honestly.")
    csv_files = st.file_uploader("Statement CSVs", type=["csv"],
                                 accept_multiple_files=True, key="csvs")
    if csv_files and st.button("Load CSV set", type="primary"):
        with st.spinner("Reading and classifying files…"):
            try:
                result = statements_api.upload(
                    [(f.name, f.getvalue()) for f in csv_files])
            except ApiError as error:
                st.error(str(error))
                st.stop()
        ui.remember_session(result)
        st.success(f"Loaded **{result['company_name']}** from "
                   f"{len(csv_files)} file(s).")
        st.rerun()

# ── loaded companies ─────────────────────────────────────────────────────────
sessions = statements_api.sessions()
if sessions:
    st.divider()
    st.markdown("##### Loaded companies")
    for record in sessions:
        columns = st.columns([4, 3, 2, 1])
        active = record["session_id"] == st.session_state.get("session_id")
        columns[0].write(f"{'**▸ ' if active else ''}{record['company_name']}"
                         f"{'**' if active else ''}")
        columns[1].caption(record["source_file"][:48])
        if columns[2].button("Make active", key=f"use_{record['session_id']}",
                             disabled=active):
            st.session_state["session_id"] = record["session_id"]
            st.session_state["company_name"] = record["company_name"]
            st.rerun()
        if columns[3].button("✕", key=f"del_{record['session_id']}"):
            statements_api.delete_session(record["session_id"])
            if active:
                st.session_state.pop("session_id", None)
            st.rerun()

session_id = st.session_state.get("session_id")
if not session_id:
    st.info("Upload a file to begin. Load a second company to unlock peer "
            "comparison.")
    st.stop()

# ── review ───────────────────────────────────────────────────────────────────
st.divider()
with st.spinner("Running checks…"):
    try:
        report = statements_api.review(session_id)
    except ApiError as error:
        st.error(str(error))
        st.stop()

ui.page_header(report["company_name"],
               f"{', '.join(report['periods_checked'])} · INR Crore")
ui.verdict_banner(report)

summary = report["summary"]
columns = st.columns(5)
for column, (label, key) in zip(columns, [
    ("Total checks", "total_checks"), ("Passed", "PASS"),
    ("Warnings", "WARN"), ("Failed", "FAIL"), ("Notes", "INFO"),
]):
    column.metric(label, summary[key])

st.markdown("##### Findings by category")
ui.findings_by_category(report)

st.caption(f"A tolerance of ±{report['tolerance_crore']:g} crore separates "
           "rounding (WARN) from a genuine failure (FAIL). Informational rows "
           "— spelling, grammar, skipped checks — carry no pass/fail judgement.")
