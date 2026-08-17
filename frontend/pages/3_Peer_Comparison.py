"""
frontend/pages/3_Peer_Comparison.py
===================================
Page 3 — benchmark two uploaded companies against each other.

Every ratio here is recomputed from the statements, not read from the
companies' own published ratio sheets.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from frontend.statements_client import ApiError, statements_api
from frontend import ui

ui.page_setup("Peer Comparison", "⚖️")
session_id, company = ui.require_session()
ui.sidebar_status()
ui.page_header("Peer comparison", "Two companies, same metrics, same year")

sessions = statements_api.sessions()
others = [s for s in sessions if s["session_id"] != session_id]
if not others:
    st.warning("Upload a second company on the **Upload & Review** page to "
               "compare.")
    st.stop()

names = {s["session_id"]: s["company_name"] for s in others}
peer_id = st.selectbox("Compare against", list(names),
                       format_func=lambda sid: names[sid])

try:
    comparison = statements_api.compare(session_id, peer_id)
except ApiError as error:
    st.error(str(error))
    st.stop()

first, second = comparison["companies"]
scorecard = comparison["scorecard"]

columns = st.columns(3)
columns[0].metric(first, f"{scorecard['wins'][first]} metrics led")
columns[1].metric(second, f"{scorecard['wins'][second]} metrics led")
columns[2].metric("Metrics scored", scorecard["metrics_scored"],
                  help="Credit-to-deposit and effective tax rate are shown "
                       "but not scored — neither is better simply for being "
                       "higher or lower.")

st.markdown("##### Every metric")
st.dataframe(pd.DataFrame([{
    "Metric": row["label"],
    first: ui.render_metric(row, first),
    second: ui.render_metric(row, second),
    "Stronger": row["leader"] or "not scored",
} for row in comparison["metrics"]]), use_container_width=True,
    hide_index=True)

st.info("Leading on more metrics does not make a company a better "
        "investment. Scale and growth usually trade against each other, and "
        "the two often lead on different measures.")
