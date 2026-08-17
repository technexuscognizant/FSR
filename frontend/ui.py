"""
frontend/ui.py
==============
Shared look and feel: page furniture, badges, and the two blocks that appear
on more than one page (the findings table and a narrative section). Keeping
them here is what lets each page file stay short and readable.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

NAVY, GREY = "#1B2A4A", "#64748B"
STATUS_ICON = {"PASS": "🟢", "WARN": "🟡", "FAIL": "🔴", "INFO": "⚪"}
RISK_ICON = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}


def page_setup(title: str, icon: str = "🏦") -> None:
    st.set_page_config(page_title=f"{title} · Statement Reviewer",
                       page_icon=icon, layout="wide")


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"<h2 style='margin-bottom:0;color:{NAVY}'>{title}</h2>"
        + (f"<p style='color:{GREY};margin-top:4px'>{subtitle}</p>"
           if subtitle else ""),
        unsafe_allow_html=True)


def remember_session(result: Dict[str, Any]) -> None:
    st.session_state["session_id"] = result["session_id"]
    st.session_state["company_name"] = result["company_name"]


def require_session() -> tuple[str, str]:
    """Pages after the first need a company loaded. Send the user back."""
    session_id = st.session_state.get("session_id")
    if not session_id:
        st.warning("No company loaded. Open **Upload & Review** first.")
        st.stop()
    return session_id, st.session_state.get("company_name", "")


def sidebar_status() -> None:
    with st.sidebar:
        st.markdown("### Loaded")
        name = st.session_state.get("company_name")
        st.write(f"**{name}**" if name else "_nothing yet_")
        st.divider()
        st.caption("All arithmetic is computed in Python. The language model "
                   "only writes commentary about verified figures.")


def verdict_banner(report: Dict[str, Any]) -> None:
    summary = report["summary"]
    if summary["FAIL"]:
        st.error(f"**{report['verdict']}** — {summary['FAIL']} failed "
                 f"check(s), {summary['root_cause_failures']} distinct "
                 f"defect(s).")
    elif summary["WARN"]:
        st.warning(f"**{report['verdict']}** — {summary['WARN']} rounding "
                   f"difference(s) noted.")
    else:
        st.success(f"**{report['verdict']}** — all "
                   f"{summary['total_checks']} checks passed.")


def findings_by_category(report: Dict[str, Any]) -> None:
    """
    One expander per category (A–E), opened by default when it contains
    something the reviewer needs to look at.
    """
    categories = sorted({f["category"] for f in report["findings"]})

    for category in categories:
        items = [f for f in report["findings"] if f["category"] == category]
        fails = sum(1 for f in items if f["status"] == "FAIL")
        warns = sum(1 for f in items if f["status"] == "WARN")
        infos = sum(1 for f in items if f["status"] == "INFO")
        badge = (f"🔴 {fails} fail" if fails else f"🟡 {warns} warn" if warns
                 else f"⚪ {infos} note" if infos else "🟢 clean")

        with st.expander(f"{category}  —  {badge}",
                         expanded=bool(fails or warns)):
            hide_knock_on = st.checkbox(
                "Hide knock-on failures", value=True, key=f"hide_{category}",
                help="One bad cell can break several checks. This shows only "
                     "the root cause of each defect.")
            shown = [f for f in items if f["root_cause"] or not hide_knock_on]
            if not shown:
                st.write("Nothing to show.")
                continue

            st.dataframe(pd.DataFrame([{
                "": STATUS_ICON.get(f["status"], "⚪"),
                "Period": f["period"],
                "Statement": f["statement"],
                "Rule": f["rule"],
                "Expected": f["expected"],
                "Found": f["found"],
                "Difference": f["delta"],
                "Root cause": "Yes" if f["root_cause"] else "No",
                "Note": f["note"],
            } for f in shown]), use_container_width=True, hide_index=True,
                column_config={
                    "Expected": st.column_config.NumberColumn(format="%.2f"),
                    "Found": st.column_config.NumberColumn(format="%.2f"),
                    "Difference": st.column_config.NumberColumn(format="%.2f"),
                    "Note": st.column_config.TextColumn(width="large"),
                })


def _source_label(source: str) -> str:
    """Readable provenance. The raw tag is a developer detail."""
    if source.startswith("gemini:"):
        return f"AI ({source.split(':', 1)[1]})"
    if source.startswith("template_fallback"):
        return "engine-written (AI unavailable)"
    if source == "template_no_api_key":
        return "engine-written (no AI configured)"
    return "engine-written"


def narrative_section(section: Dict[str, Any]) -> None:
    flagged = section["number_check"] == "FLAGGED"
    icon = RISK_ICON.get(section["risk_level"], "⚪")
    label = (f"{icon} {section['section_code']} · {section['heading']}"
             + ("   ⚠️ unverified figures" if flagged else ""))
    with st.expander(label, expanded=True):
        st.write(section["commentary"])
        left, right = st.columns([3, 2])
        left.caption(f"Risk: **{section['risk_level']}** · "
                     f"Source: {_source_label(section['source'])}")
        if flagged:
            right.error("Unverified: " + ", ".join(section["unverified_numbers"]))
        else:
            right.caption("Every figure checked ✓")


def render_metric(row: Dict[str, Any], company: str) -> str:
    """
    Format one peer-comparison cell.

    The backend sends percentages as fractions (0.2711). Formatting happens
    here, at the edge, and nowhere else.
    """
    value = row["values"].get(company)
    if value is None:
        return "—"
    if row["unit"] == "percent":
        return f"{value * 100:.2f}%"
    if row["unit"] == "crore":
        return f"₹{value:,.0f} Cr"
    return f"{value:,.2f}"