"""Page 12 – Thresholds (Green / Amber / Red monitoring boundaries, editable)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import df, flash, how_it_works, page_header
from database import repository as repo
from database.database import get_session
from performance.thresholds import rag_status, threshold_text, validate_threshold
from utils.helpers import pct, rag_emoji


def render() -> None:
    page_header("Thresholds", "Green / Amber / Red monitoring thresholds for each performance metric.")
    st.warning("These are **prototype monitoring thresholds** chosen for demonstration. They are not regulatory or industry-mandated values.")
    how_it_works(
        "Each metric has a direction (*higher is better* for HIT rate / precision / recall; *lower is better* for review, dispute, "
        "error and false rates) and two boundaries. The Executive Dashboard colours its KPI cards and trend charts with these values. "
        "Changing a threshold is written to the audit log (THRESHOLD_CHANGED)."
    )
    with get_session() as session:
        thresholds = repo.get_thresholds(session)
        runs = repo.runs_frame(session)
    latest = runs.sort_values(["timestamp", "run_id"]).iloc[-1] if not runs.empty else None

    st.subheader("Current status (latest run)")
    rows = []
    for t in thresholds:
        value = latest[t.metric] if latest is not None and t.metric in latest else None
        status = rag_status(value, t.direction, t.green, t.amber)
        txt = threshold_text(t.direction, t.green, t.amber)
        rows.append({"Metric": t.label, "Direction": t.direction.replace("_", " "), "Green": txt["GREEN"], "Amber": txt["AMBER"], "Red": txt["RED"],
                     "Latest value": pct(value), "Status": f"{rag_emoji(status)} {status or 'n/a'}"})
    df(pd.DataFrame(rows))

    st.subheader("Edit thresholds")
    with st.form("thresholds_form"):
        edits = {}
        for t in thresholds:
            c = st.columns([2, 2, 1.5, 1.5])
            c[0].markdown(f"**{t.label}**")
            c[1].caption("higher is better" if t.direction == "higher_is_better" else "lower is better")
            g = c[2].number_input("Green boundary (%)", 0.0, 100.0, float(t.green), 0.5, key=f"g_{t.metric}")
            a = c[3].number_input("Amber boundary (%)", 0.0, 100.0, float(t.amber), 0.5, key=f"a_{t.metric}")
            edits[t.metric] = (g, a, t.direction, t.label)
        saved = st.form_submit_button("💾 Save thresholds", type="primary")
    if saved:
        problems = [f"{label}: {err}" for metric, (g, a, d, label) in edits.items() if (err := validate_threshold(d, g, a))]
        if problems:
            for p in problems:
                st.error(p)
        else:
            with get_session() as session:
                for metric, (g, a, _, _) in edits.items():
                    repo.update_threshold(session, metric, g, a)
            flash("Thresholds saved.")
            st.rerun()
