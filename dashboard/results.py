"""Page 6 – Match Results (browse a run, filter by decision / scenario, drill into one record)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard.common import df, flash, get_active_config, get_index, how_it_works, page_header, render_outcome, stored_to_view
from database import repository as repo
from database.database import get_session
from utils.helpers import df_to_excel_bytes, pct
from workflows.runner import run_batch


def select_run(key: str = "selected_run_id", label: str = "Matching run") -> str | None:
    """Run selector shared by several pages. Returns run_id or None."""
    with get_session() as session:
        runs = repo.runs_frame(session)
    if runs.empty:
        return None
    runs = runs.sort_values(["timestamp", "run_id"], ascending=False)
    options = runs["run_id"].tolist()
    labels = {r.run_id: f"{r.run_id} · batch {r.batch_id} · v{r.algorithm_version} · {r.total_records} records · {r.timestamp:%d %b %H:%M}"
              for r in runs.itertuples()}
    default = st.session_state.get(key)
    index = options.index(default) if default in options else 0
    chosen = st.selectbox(label, options, index=index, format_func=lambda x: labels[x])
    st.session_state[key] = chosen
    return chosen


def render() -> None:
    page_header("Match Results", "Every incoming record of a run with its best candidate, score, confidence, conflict flag and decision.")
    how_it_works(
        "Select a run, filter by decision or generator scenario, then pick a record to open the full explanation: "
        "normalization, blocking passes, exact rules, field-level sub-scores, weight calculation, conflicts, ranking, "
        "score gap, confidence points and the decision rule.\n\n"
        "Use the scenario filter to demonstrate each of the 12 test scenarios (S1 exact match … S12 noisy data). "
        "A batch can be re-run with the currently active algorithm version – a new run is created, history is never overwritten."
    )

    # --------------------------------------------- run batch (if needed)
    with get_session() as session:
        batches = repo.list_batches(session)
    if batches.empty:
        st.warning("No incoming data yet. Use the Incoming Data Generator or Batch Upload.")
        return
    cfg = get_active_config()
    with st.expander("Run / re-run a batch with the active algorithm version", expanded=bool((batches["runs"] == 0).any())):
        b = st.selectbox("Batch", batches["batch_id"].tolist(),
                         format_func=lambda x: f"{x} · {batches.set_index('batch_id').loc[x, 'records']} records · "
                                               f"{batches.set_index('batch_id').loc[x, 'runs']} run(s)")
        if st.button(f"▶️ RUN SEARCH & MATCH on {b} with v{cfg.version_name}", type="primary"):
            with st.spinner("Matching…"):
                summary = run_batch(b, cfg=cfg, index=get_index(), run_type="rerun" if batches.set_index("batch_id").loc[b, "runs"] else "batch")
            st.session_state["selected_run_id"] = summary.run_id
            flash(f"Run {summary.run_id}: {summary.counts['MATCH']} MATCH · {summary.counts['MANUAL_REVIEW']} MANUAL_REVIEW · "
                  f"{summary.counts['NO_MATCH']} NO_MATCH in {summary.duration_ms:.0f} ms.")
            st.rerun()

    run_id = select_run()
    if run_id is None:
        st.info("No run yet – run a batch above.")
        return
    with get_session() as session:
        run = repo.get_run(session, run_id)
        results = repo.results_frame(session, run_id)
    if results.empty:
        st.info("This run has no results.")
        return

    # ------------------------------------------------------- KPI strip
    c = st.columns(7)
    c[0].metric("Records", run.total_records)
    c[1].metric("MATCH", run.total_matches)
    c[2].metric("MANUAL_REVIEW", run.total_manual_reviews)
    c[3].metric("NO_MATCH", run.total_no_matches)
    c[4].metric("HIT rate", pct(run.hit_rate))
    c[5].metric("Avg candidates", run.avg_candidates if run.avg_candidates is not None else "-")
    c[6].metric("Candidate reduction", pct(run.candidate_reduction_pct, 2))

    col1, col2 = st.columns([1, 1])
    with col1:
        st.plotly_chart(charts.decision_distribution({"MATCH": run.total_matches, "MANUAL_REVIEW": run.total_manual_reviews,
                                                      "NO_MATCH": run.total_no_matches}, f"Run {run_id}"), width="stretch")
    with col2:
        with get_session() as session:
            version = repo.get_version(session, run.algorithm_version)
        st.plotly_chart(charts.score_histogram(results["Overall Score"], version.match_threshold, version.manual_review_threshold), width="stretch")

    # ---------------------------------------------------------- filters
    st.subheader("Results")
    f1, f2, f3 = st.columns([2, 2, 2])
    decisions = f1.multiselect("Decision", ["MATCH", "MANUAL_REVIEW", "NO_MATCH"], default=["MATCH", "MANUAL_REVIEW", "NO_MATCH"])
    scenarios = sorted([s for s in results["Scenario"].dropna().unique() if s])
    scenario = f2.multiselect("Scenario (generator batches only)", scenarios, default=[])
    text = f3.text_input("Search name / ID")
    view = results[results["Decision"].isin(decisions)]
    if scenario:
        view = view[view["Scenario"].isin(scenario)]
    if text:
        mask = view[["Incoming Name", "Incoming ID", "Entity ID", "Best Candidate"]].astype(str).apply(
            lambda col: col.str.contains(text, case=False, na=False)).any(axis=1)
        view = view[mask]

    show_cols = ["Row", "Incoming ID", "Incoming Name", "Scenario", "Best Candidate", "Entity ID", "Overall Score", "Score Gap",
                 "Confidence", "Conflict", "Decision", "True Entity", "True Decision", "Reason"]
    df(view[show_cols], column_config={
        "Overall Score": st.column_config.ProgressColumn("Overall Score", min_value=0, max_value=100, format="%.1f"),
        "Score Gap": st.column_config.NumberColumn(format="%.1f"),
    })
    st.download_button("⬇️ Download these results (.xlsx)", df_to_excel_bytes({"results": view[show_cols]}),
                       file_name=f"matched_results_{run_id}.xlsx")

    # ------------------------------------------------------- drill down
    st.subheader("Open a record")
    if view.empty:
        st.info("No records match the filters.")
        return
    labels = {r["Incoming ID"]: f"{r['Incoming ID']} · {r['Incoming Name']} · {r['Decision']} · {r['Overall Score'] if pd.notna(r['Overall Score']) else '-'}"
              for _, r in view.iterrows()}
    chosen = st.selectbox("Incoming record", list(labels.keys()), format_func=lambda x: labels[x])
    row = view[view["Incoming ID"] == chosen].iloc[0]
    with get_session() as session:
        result = repo.get_result(session, int(row["match_id"]))
        cands = repo.get_candidates(session, run_id, chosen)
        incoming = repo.get_incoming(session, chosen).to_dict()
    if row["Scenario"]:
        st.caption(f"Generator scenario: **{row['Scenario']}**" + (f" · ground truth: {row['True Decision']} {row['True Entity']}" if row["True Decision"] else ""))
    render_outcome(stored_to_view(result, cands, incoming))
