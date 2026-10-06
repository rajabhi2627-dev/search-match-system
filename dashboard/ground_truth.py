"""Page 11 – Ground Truth (upload labels, evaluate a run: confusion matrix, precision, recall, F1, FPR, FNR, accuracy)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard.common import df, flash, how_it_works, page_header
from dashboard.results import select_run
from data.excel_loader import ground_truth_template
from database import repository as repo
from database.database import get_session
from performance.ground_truth import confusion_matrix_frame, evaluate, outcome_table, parse_ground_truth_file
from performance.metrics import GT_UNAVAILABLE, candidate_recall
from utils.helpers import df_to_excel_bytes, pct


def render() -> None:
    page_header("Ground Truth", "Labelled 'correct answers' used ONLY to measure the matching algorithm – not an AI validation framework.")
    how_it_works(
        "A ground-truth (golden) dataset says, for each `incoming_id`, which `true_entity_id` it belongs to and the `true_decision` "
        "(MATCH or NO_MATCH). Labels come from three places: the **Incoming Data Generator** (it knows the source record), "
        "**human reviews** (a confirmed decision becomes a label) and **uploads** on this page.\n\n"
        "Comparing the run output with the labels gives TP / FP / FN / TN and therefore precision, recall, F1, FPR, FNR and accuracy. "
        "MANUAL_REVIEW records are deferred decisions and are excluded from the confusion matrix (shown separately)."
    )
    with get_session() as session:
        gt = repo.ground_truth_frame(session)

    c1, c2 = st.columns(2)
    c1.metric("Ground-truth labels stored", len(gt))
    c2.download_button("⬇️ Download label template (.xlsx)", df_to_excel_bytes({"ground_truth": ground_truth_template()}), file_name="ground_truth_template.xlsx")

    st.subheader("Upload labels")
    uploaded = st.file_uploader("Labelled dataset (.xlsx / .csv) with incoming_id, true_entity_id, true_decision", type=["xlsx", "csv"])
    if uploaded is not None:
        rows, errors = parse_ground_truth_file(uploaded, uploaded.name)
        for e in errors[:20]:
            st.warning(e)
        if rows:
            st.write(f"{len(rows)} valid label(s) found.")
            if st.button("💾 Save labels", type="primary"):
                with get_session() as session:
                    repo.upsert_ground_truth(session, rows, source="upload")
                    repo.recompute_all_runs(session)
                flash(f"{len(rows)} labels saved and all run metrics recomputed.")
                st.rerun()

    st.subheader("Evaluate a run against ground truth")
    run_id = select_run(key="gt_run_id")
    if run_id is None:
        st.info("No matching run yet.")
        return
    with get_session() as session:
        results = repo.get_results(session, run_id)
        truth = repo.get_ground_truth(session, [r["incoming_id"] for r in results])
        cands = repo.candidates_by_incoming(session, run_id)
        run = repo.get_run(session, run_id)
    if not truth:
        st.warning(GT_UNAVAILABLE + " Upload labels for the incoming IDs of this run, or generate a batch with labels.")
        return

    ev = evaluate(results, truth)
    c, m = ev["counts"], ev["metrics"]
    st.caption(f"{c['labelled']} of {len(results)} records are labelled · {c['REVIEW']} MANUAL_REVIEW records excluded from the matrix "
               f"({c['review_true_match']} of them are true matches awaiting a human).")
    k = st.columns(4)
    k[0].metric("TP", c["TP"]); k[1].metric("FP", c["FP"]); k[2].metric("FN", c["FN"]); k[3].metric("TN", c["TN"])
    k = st.columns(6)
    k[0].metric("Precision", pct(m["precision"])); k[1].metric("Recall", pct(m["recall"])); k[2].metric("F1 Score", pct(m["f1_score"]))
    k[3].metric("False Positive Rate", pct(m["false_positive_rate"])); k[4].metric("False Negative Rate", pct(m["false_negative_rate"]))
    k[5].metric("Accuracy", pct(m["accuracy"]))
    k = st.columns(3)
    k[0].metric("HIT Rate (label-free)", pct(run.hit_rate), help="Best candidate ≥ review threshold / total – does the search find candidates?")
    k[1].metric("Candidate recall (true entity in top-N)", pct(candidate_recall(cands, truth)), help="Was the correct entity anywhere in the candidate list?")
    k[2].metric("Precision (label-based)", pct(m["precision"]), help="Of automatic MATCH decisions, how many were correct?")
    st.info("**HIT Rate vs Precision:** HIT Rate measures whether the search process finds candidates at all. Precision measures how many "
            "of the predicted matches are actually correct – it needs ground truth.")

    left, right = st.columns([1, 2])
    with left:
        st.plotly_chart(charts.confusion_heatmap(confusion_matrix_frame(c)), width="stretch")
    with right:
        table = outcome_table(results, truth, ev["outcomes"])
        pick = st.multiselect("Show outcomes", ["TP", "FP", "FN", "TN", "REVIEW", "UNLABELLED"], default=["FP", "FN"])
        df(table[table["Outcome"].isin(pick)] if pick else table)
        st.caption("FP = wrong automatic match (bad for trust). FN = missed match (bad for coverage). Open the record on the Match Results page to see why.")

    with st.expander("All stored labels"):
        df(gt)
