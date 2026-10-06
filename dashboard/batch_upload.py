"""Page 3 – Batch Upload (Excel / CSV → validation → matching → downloadable results)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import df, get_active_config, get_index, how_it_works, page_header
from data.excel_loader import dataframe_to_records, incoming_template, load_incoming_file
from data.validators import validate_incoming_df
from database import repository as repo
from database.database import get_session
from utils.helpers import df_to_excel_bytes, pct
from workflows.runner import store_upload_and_run


def render() -> None:
    page_header("Batch Upload", "Upload an .xlsx or .csv file of incoming records; every row is validated, matched and explained.")
    how_it_works(
        "1. The file is read and column names are mapped to the standard fields (aliases such as *Mobile*, *E-mail*, *DOB*, *Pincode* are recognised).\n"
        "2. **Validation**: required columns (name + at least one of email / phone / address), empty file, duplicate rows, "
        "unparseable dates, invalid phones/emails.\n"
        "3. **Data quality** is profiled (missing %, invalid %, duplicates %) so weak results can be explained.\n"
        "4. The rows are stored as a batch and run through the full pipeline with the active algorithm version.\n"
        "5. The result table shows one line per row and can be downloaded as `matched_results.xlsx`."
    )

    with get_session() as session:
        master_n = repo.master_count(session)
    if master_n == 0:
        st.warning("The master database is empty. Generate master data first (Master Data page).")
        return

    st.download_button("⬇️ Download upload template (.xlsx)", df_to_excel_bytes({"incoming": incoming_template()}),
                       file_name="incoming_template.xlsx")
    uploaded = st.file_uploader("Upload incoming records", type=["xlsx", "csv"])
    if uploaded is None:
        _show_last_results()
        return

    data, mapping = load_incoming_file(uploaded, uploaded.name)
    report = validate_incoming_df(data)

    st.subheader("Validation")
    if mapping:
        st.caption("Column mapping: " + ", ".join(f"`{k}` → `{v}`" for k, v in mapping.items() if k != v) or "all columns recognised as-is")
    for e in report.errors:
        st.error(e)
    for w in report.warnings:
        st.warning(w)
    if not report.is_valid:
        return
    st.success(f"File is valid: {report.row_count} rows.")

    st.subheader("Input data quality")
    q = report.quality
    cols = st.columns(7)
    for col, (key, label) in zip(cols, [("missing_name_pct", "Missing name"), ("missing_email_pct", "Missing email"),
                                        ("missing_phone_pct", "Missing phone"), ("missing_address_pct", "Missing address"),
                                        ("duplicate_input_pct", "Duplicate rows"), ("invalid_email_pct", "Invalid email"),
                                        ("invalid_phone_pct", "Invalid phone")]):
        col.metric(label, pct(q.get(key)))

    with st.expander("Preview (first 20 rows)"):
        df(data.head(20))

    cfg = get_active_config()
    if st.button(f"▶️ RUN SEARCH & MATCH on {report.row_count} rows (algorithm v{cfg.version_name})", type="primary"):
        records = dataframe_to_records(data)
        with st.spinner("Matching…"):
            summary = store_upload_and_run(records, uploaded.name, cfg=cfg, index=get_index())
        st.session_state["upload_last_run"] = summary.run_id
        st.success(f"Run {summary.run_id} complete on batch {summary.batch_id}: "
                   f"{summary.counts['MATCH']} MATCH · {summary.counts['MANUAL_REVIEW']} MANUAL_REVIEW · {summary.counts['NO_MATCH']} NO_MATCH "
                   f"in {summary.duration_ms:.0f} ms.")
    _show_last_results()


def _show_last_results() -> None:
    run_id = st.session_state.get("upload_last_run")
    if not run_id:
        return
    with get_session() as session:
        results = repo.results_frame(session, run_id)
        run = repo.get_run(session, run_id)
    if results.empty:
        return
    st.subheader(f"Results for run {run_id}")
    c = st.columns(5)
    c[0].metric("Rows", run.total_records)
    c[1].metric("MATCH", run.total_matches)
    c[2].metric("MANUAL_REVIEW", run.total_manual_reviews)
    c[3].metric("NO_MATCH", run.total_no_matches)
    c[4].metric("HIT rate", pct(run.hit_rate))
    show_cols = ["Row", "Incoming Name", "Best Candidate", "Entity ID", "Overall Score", "Score Gap", "Confidence", "Conflict", "Decision", "Reason"]
    df(results[show_cols], column_config={"Overall Score": st.column_config.NumberColumn(format="%.1f"),
                                           "Score Gap": st.column_config.NumberColumn(format="%.1f")})
    export = results[["Row", "Incoming ID", "Incoming Name", "Best Candidate", "Entity ID", "Overall Score", "Score Gap",
                      "Confidence", "Conflict", "Decision", "Reason", "Candidates"]]
    st.download_button("⬇️ DOWNLOAD RESULTS (matched_results.xlsx)", df_to_excel_bytes({"results": export}),
                       file_name="matched_results.xlsx", type="primary")
    st.caption("Open the *Match Results* page to drill into any row, or *Manual Review* / *Merge Review* to act on it.")
