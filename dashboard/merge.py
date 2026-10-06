"""Page 8 – Merge Review (controlled, field-by-field merge of MATCH records into the master)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import df, flash, how_it_works, page_header
from dashboard.results import select_run
from database import repository as repo
from database.database import get_session
from matching.merge_engine import build_merged_record, compare_records, default_choices
from utils.helpers import RECORD_FIELDS

STATUS_ICON = {"SAME": "＝", "FORMAT_ONLY": "≈", "DIFFERENT": "≠", "INCOMING_FILLS_BLANK": "＋", "MASTER_ONLY": "·"}
STATUS_TEXT = {"SAME": "identical", "FORMAT_ONLY": "same after normalization (format only)", "DIFFERENT": "DIFFERENT",
               "INCOMING_FILLS_BLANK": "incoming fills a blank", "MASTER_ONLY": "only master has a value"}


def render() -> None:
    page_header("Merge Review", "Review & Merge: compare the master record with the incoming record and decide what survives.")
    how_it_works(
        "Nothing is merged automatically. For every MATCH (or human-confirmed match) the page shows **master vs incoming** "
        "field by field and highlights differences: *identical*, *format only* (e.g. `+91-9876543210` vs `9876543210`), "
        "*different*, or *incoming fills a blank*.\n\n"
        "Default survivorship rule: keep master values, fill blanks from incoming. You can override per field. "
        "**CONFIRM MERGE** updates the master and stores old/new values in `merge_history`; **REJECT MERGE** stores the rejection "
        "(and counts as a dispute). A confirmed merge can later be **reversed**, which restores the master and counts as a merge error."
    )
    run_id = select_run()
    if run_id is None:
        st.warning("No matching run yet.")
        return
    with get_session() as session:
        results = repo.results_frame(session, run_id)
        merged_ids = repo.merged_match_ids(session, run_id)
        reviews = repo.reviews_frame(session, run_id)
    if results.empty:
        st.info("No results in this run.")
        return

    confirmed_by_review = set(reviews[reviews["Reviewer Decision"] == "CONFIRM_MATCH"]["Incoming ID"]) if not reviews.empty else set()
    eligible = results[(results["Decision"] == "MATCH") | (results["Incoming ID"].isin(confirmed_by_review))]
    eligible = eligible[eligible["Entity ID"] != "-"]
    eligible["Merged/Decided"] = eligible["match_id"].isin(merged_ids)
    pending = eligible[~eligible["Merged/Decided"]]

    c = st.columns(3)
    c[0].metric("Eligible for merge", len(eligible))
    c[1].metric("Pending", len(pending))
    c[2].metric("Decided", int(eligible["Merged/Decided"].sum()))

    scope = st.radio("Show", ["Pending merges", "All eligible"], horizontal=True)
    pool = pending if scope == "Pending merges" else eligible
    if pool.empty:
        st.success("No pending merges.")
        _history(run_id)
        return
    df(pool[["Row", "Incoming ID", "Incoming Name", "Best Candidate", "Entity ID", "Overall Score", "Confidence", "Decision", "Merged/Decided"]])

    labels = {r["Incoming ID"]: f"{r['Incoming ID']} · {r['Incoming Name']} → {r['Entity ID']} ({r['Best Candidate']}) · {r['Overall Score']}" for _, r in pool.iterrows()}
    chosen = st.selectbox("Select a record", list(labels), format_func=lambda x: labels[x])
    row = pool[pool["Incoming ID"] == chosen].iloc[0]
    with get_session() as session:
        result = repo.get_result(session, int(row["match_id"]))
        master = repo.get_master(session, result["entity_id"]).to_dict()
        incoming = repo.get_incoming(session, chosen).to_dict()

    st.subheader(f"MASTER {result['entity_id']}  versus  INCOMING {chosen}")
    diffs = compare_records(master, incoming)
    defaults = default_choices(diffs)
    choices: dict[str, str] = {}
    header = st.columns([1.3, 2.5, 2.5, 2, 1.5])
    for col, title in zip(header, ["Field", "Master record", "Incoming record", "Difference", "Keep"]):
        col.markdown(f"**{title}**")
    for d in diffs:
        cols = st.columns([1.3, 2.5, 2.5, 2, 1.5])
        cols[0].write(d.label)
        cols[1].code(d.master_value or "—", language=None)
        cols[2].code(d.incoming_value or "—", language=None)
        text = f"{STATUS_ICON[d.status]} {STATUS_TEXT[d.status]}"
        if d.status == "DIFFERENT":
            cols[3].error(text)
        elif d.status in ("FORMAT_ONLY", "INCOMING_FILLS_BLANK"):
            cols[3].warning(text)
        else:
            cols[3].caption(text)
        if d.status in ("DIFFERENT", "FORMAT_ONLY", "INCOMING_FILLS_BLANK"):
            choices[d.field] = cols[4].radio("keep", ["master", "incoming"], index=0 if defaults[d.field] == "master" else 1,
                                             key=f"merge_{chosen}_{d.field}", horizontal=True, label_visibility="collapsed")
        else:
            choices[d.field] = "master"
            cols[4].caption("master")

    merged = build_merged_record(master, incoming, choices)
    with st.expander("Preview of the merged master record"):
        df(pd.DataFrame({"Field": RECORD_FIELDS, "Before": [master.get(f) or "" for f in RECORD_FIELDS],
                         "After": [merged.get(f) or "" for f in RECORD_FIELDS]}))

    already = bool(row["Merged/Decided"])
    if already:
        st.info("A merge decision already exists for this record (see history below).")
    reason = st.text_input("Reason / comment", key=f"merge_reason_{chosen}")
    actor = st.text_input("Your name", value="reviewer", key=f"merge_actor_{chosen}")
    b1, b2 = st.columns(2)
    if b1.button("✅ CONFIRM MERGE", type="primary", disabled=already):
        with get_session() as session:
            repo.confirm_merge(session, result, choices, reason or "Confirmed in Merge Review", actor or "reviewer")
        flash(f"Merged {chosen} into {result['entity_id']}. Master record updated; old and new values stored in merge_history.")
        st.cache_resource.clear()      # master changed → rebuild blocking index next time
        st.rerun()
    if b2.button("❌ REJECT MERGE", disabled=already):
        with get_session() as session:
            repo.reject_merge(session, result, reason or "Rejected in Merge Review", actor or "reviewer")
        flash(f"Merge of {chosen} rejected. Recorded as a dispute.", kind="warning")
        st.rerun()
    _history(run_id)


def _history(run_id: str) -> None:
    st.subheader("Merge history")
    with get_session() as session:
        hist = repo.merges_frame(session, run_id)
        confirmed = [m for m in repo.confirmed_merges(session) if m.run_id == run_id]
    if hist.empty:
        st.caption("No merge actions yet.")
        return
    df(hist.drop(columns=["Old Values", "New Values"]))
    with st.expander("Old / new values (JSON)"):
        df(hist[["Merge ID", "Incoming ID", "Entity ID", "Action", "Old Values", "New Values"]])
    reversible = [m for m in confirmed if not m.is_error]
    if reversible:
        st.markdown("**Reverse a confirmed merge** (restores the master record; counts as a dispute and a merge error)")
        pick = st.selectbox("Merge to reverse", [m.merge_id for m in reversible],
                            format_func=lambda i: next(f"#{m.merge_id} · {m.incoming_id} → {m.entity_id} · {m.merge_timestamp:%d %b %H:%M}" for m in reversible if m.merge_id == i))
        why = st.text_input("Reason for reversal")
        if st.button("↩️ REVERSE MERGE"):
            with get_session() as session:
                repo.reverse_merge(session, int(pick), why or "Reversed in Merge Review", "reviewer")
            st.cache_resource.clear()
            flash("Merge reversed and master record restored.")
            st.rerun()
