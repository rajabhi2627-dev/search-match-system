"""Page 13 – Audit Log."""
from __future__ import annotations

import streamlit as st

from dashboard.common import df, how_it_works, page_header
from database import repository as repo
from database.database import get_session
from utils.helpers import df_to_excel_bytes


def render() -> None:
    page_header("Audit Log", "Who did what, when – every important action is recorded.")
    how_it_works(
        "Tracked actions include DATA_GENERATED, FILE_UPLOADED, MATCH_RUN, SEARCH, ALGORITHM_CREATED, ALGORITHM_ACTIVATED, "
        "THRESHOLD_CHANGED, MANUAL_REVIEW, MERGE_CONFIRMED, MERGE_REJECTED, MERGE_REVERSED, GROUND_TRUTH_LOADED, "
        "REGRESSION_TEST, STABILITY_TEST and DATA_CLEARED. Old and new values are stored as JSON where applicable."
    )
    with get_session() as session:
        types = sorted(repo.audit_action_types(session))
    c1, c2 = st.columns([2, 1])
    chosen = c1.selectbox("Action type", ["All"] + types)
    limit = c2.number_input("Rows", 50, 5000, 500, 50)
    with get_session() as session:
        logs = repo.audit_logs(session, limit=int(limit), action_type=None if chosen == "All" else chosen)
    if logs.empty:
        st.info("No audit entries yet.")
        return
    text = st.text_input("Search")
    if text:
        mask = logs.astype(str).apply(lambda col: col.str.contains(text, case=False, na=False)).any(axis=1)
        logs = logs[mask]
    st.caption(f"{len(logs)} entries")
    df(logs)
    st.download_button("⬇️ Download audit log (.xlsx)", df_to_excel_bytes({"audit": logs}), file_name="audit_log.xlsx")
