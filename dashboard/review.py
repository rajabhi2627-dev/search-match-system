"""Page 7 – Manual Review (human decisions on MANUAL_REVIEW records – and on any other record)."""
from __future__ import annotations

import streamlit as st

from dashboard.common import df, flash, how_it_works, page_header, record_frame, render_outcome, stored_to_view
from dashboard.results import select_run
from database import repository as repo
from database.database import get_session

REVIEW_OPTIONS = {
    "CONFIRM_MATCH": "✅ CONFIRM MATCH – the best candidate is the same person",
    "REJECT_MATCH": "❌ REJECT MATCH – the best candidate is NOT this person",
    "MARK_NO_MATCH": "🚫 MARK NO MATCH – none of the candidates is this person",
    "SELECT_DIFFERENT_ENTITY": "🔁 SELECT DIFFERENT ENTITY – another candidate is the right one",
}


def render() -> None:
    page_header("Manual Review", "Records the engine could not decide automatically are queued here for a human decision.")
    how_it_works(
        "A record lands in manual review when (a) its score is between the review and match thresholds, (b) the score is high but a "
        "**critical conflict** exists (e.g. phone matches, email contradicts), or (c) the score is high but the **gap** to the second "
        "candidate is too small (ambiguous).\n\n"
        "The reviewer sees the incoming record, the top candidates with component scores, confidence, conflicts and the reason, "
        "then records a decision. Decisions are stored in `human_review`, become **ground truth** for the record, and – when they "
        "contradict an automatic MATCH – count as a **dispute**."
    )
    run_id = select_run()
    if run_id is None:
        st.warning("No matching run yet.")
        return
    with get_session() as session:
        results = repo.results_frame(session, run_id)
        reviewed = repo.reviewed_match_ids(session, run_id)
    if results.empty:
        st.info("No results in this run.")
        return

    results["Reviewed"] = results["match_id"].isin(reviewed)
    queue = results[(results["Decision"] == "MANUAL_REVIEW")]
    pending = queue[~queue["Reviewed"]]

    c = st.columns(4)
    c[0].metric("Manual review queue", len(queue))
    c[1].metric("Pending", len(pending))
    c[2].metric("Reviewed", int(queue["Reviewed"].sum()))
    c[3].metric("Total reviews in run", len(reviewed))

    scope = st.radio("Show", ["Pending manual reviews", "All manual reviews", "All records (review any decision)"], horizontal=True)
    pool = pending if scope.startswith("Pending") else queue if scope.startswith("All manual") else results
    if pool.empty:
        st.success("Nothing to review in this scope.")
        _history(run_id)
        return

    df(pool[["Row", "Incoming ID", "Incoming Name", "Entity ID", "Overall Score", "Score Gap", "Confidence", "Conflict", "Decision", "Reviewed", "Reason"]],
       column_config={"Overall Score": st.column_config.NumberColumn(format="%.1f"), "Score Gap": st.column_config.NumberColumn(format="%.1f")})

    labels = {r["Incoming ID"]: f"{r['Incoming ID']} · {r['Incoming Name']} · {r['Decision']} · score {r['Overall Score']}" for _, r in pool.iterrows()}
    chosen = st.selectbox("Select a record to review", list(labels), format_func=lambda x: labels[x])
    row = pool[pool["Incoming ID"] == chosen].iloc[0]
    with get_session() as session:
        result = repo.get_result(session, int(row["match_id"]))
        cands = repo.get_candidates(session, run_id, chosen)
        incoming = repo.get_incoming(session, chosen).to_dict()
    view = stored_to_view(result, cands, incoming)

    st.subheader("Reason for review")
    st.warning(result["reason"])
    conflicts = (cands[0].get("conflicts", []) if cands else []) + view["set_conflicts"]
    for cf in conflicts:
        (st.error if cf["severity"] == "CRITICAL" else st.warning)(f"[{cf['severity']}] {cf['message']}")

    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Incoming record**")
        df(record_frame(incoming, "Incoming"))
    with right:
        render_outcome(view, show_blocking_metrics=False)

    st.subheader("Reviewer decision")
    with st.form("review_form"):
        decision = st.radio("Decision", list(REVIEW_OPTIONS), format_func=lambda k: REVIEW_OPTIONS[k])
        other = st.selectbox("Entity (for SELECT DIFFERENT ENTITY)", [c["entity_id"] for c in cands] or ["-"],
                             format_func=lambda e: next((f"{c['entity_id']} · {(c.get('master') or {}).get('name', '')} · {c['overall']}" for c in cands if c["entity_id"] == e), e))
        reviewer = st.text_input("Reviewer", value="reviewer")
        reason = st.text_area("Reason", placeholder="Why did you decide this?")
        submitted = st.form_submit_button("💾 Save review", type="primary")
    if submitted:
        if decision == "SELECT_DIFFERENT_ENTITY" and (other == "-" or other == result["entity_id"]):
            st.error("Choose a candidate that differs from the predicted entity.")
        else:
            with get_session() as session:
                repo.add_review(session, result, decision, reviewer or "reviewer", reason, actual_entity_id=other if decision == "SELECT_DIFFERENT_ENTITY" else None)
            flash(f"Review saved for {chosen}: {decision}.")
            st.rerun()
    _history(run_id)


def _history(run_id: str) -> None:
    with get_session() as session:
        hist = repo.reviews_frame(session, run_id)
    st.subheader("Review history (this run)")
    if hist.empty:
        st.caption("No reviews yet.")
    else:
        df(hist)
