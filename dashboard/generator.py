"""Pages 4 & 5 – Incoming Data Generator and Master Data."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import df, flash, get_active_config, how_it_works, page_header
from data.incoming_generator import SCENARIO_LABELS
from database import repository as repo
from database.database import get_session
from utils.helpers import df_to_excel_bytes, load_config
from workflows.runner import generate_incoming_data, generate_master_data

MASTER_PRESETS = [100, 500, 1000, 5000, 10000]


# ======================================================================
# Master Data
# ======================================================================
def render_master() -> None:
    page_header("Master Data", "The master database holds the 'golden' customer records that incoming data is matched against.")
    how_it_works(
        "The generator creates realistic **synthetic Indian-style records** (names, phones, emails, addresses, PIN codes, companies). "
        "A small share of records get a *near twin* (same name and city, different identifiers) so the ambiguous-match scenario exists.\n\n"
        "The worked example **Rahul Sharma · 9876543210 · rahul.sharma@gmail.com · 12 MG Road, Patna** is always included "
        "(entity **C01023** when 1,023+ records are generated).\n\n"
        "*Replace* clears all existing data (incoming, results, runs, reviews, merges, labels). *Append* adds to the existing master."
    )
    with get_session() as session:
        counts = repo.counts_summary(session)
        preview = repo.master_frame(session, limit=200)

    c1, c2, c3 = st.columns(3)
    c1.metric("Master records", f"{counts['master']:,}")
    c2.metric("Incoming records", f"{counts['incoming']:,}")
    c3.metric("Matching runs", counts["runs"])

    gen_cfg = load_config().get("generator", {})
    with st.form("master_form"):
        col1, col2, col3, col4 = st.columns(4)
        n = col1.selectbox("Number of records", MASTER_PRESETS, index=2, format_func=lambda x: f"{x:,}")
        seed = col2.number_input("Random seed", min_value=0, value=int(gen_cfg.get("seed", 42)),
                                 help="Same seed → same data (deterministic).")
        twin = col3.slider("Near-twin %", 0.0, 10.0, float(gen_cfg.get("twin_pct", 2)), 0.5,
                           help="Share of records that get a look-alike (same name + city).")
        mode = col4.radio("Mode", ["replace", "append"], horizontal=True)
        go = st.form_submit_button("⚙️ GENERATE MASTER DATA", type="primary")
    if go:
        with st.spinner(f"Generating {n:,} synthetic records…"):
            summary = generate_master_data(int(n), seed=int(seed), mode=mode, twin_pct=twin)
        replaced = " Existing master data and all dependent results were replaced." if (mode == "replace" and counts["master"]) else ""
        flash(f"Inserted {summary.inserted:,} records (total {summary.total:,}). "
              + (f"Worked example entity: **{summary.example_entity_id}**." if summary.example_entity_id else "")
              + replaced)
        st.rerun()

    st.subheader("Preview (first 200 records)")
    if preview.empty:
        st.info("No master data yet.")
    else:
        search = st.text_input("Filter preview by name / email / phone / city")
        if search:
            mask = preview.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            preview = preview[mask]
        df(preview)
        with get_session() as session:
            full = repo.master_frame(session)
        st.download_button("⬇️ Download full master data (.xlsx)", df_to_excel_bytes({"master": full}), file_name="master_data.xlsx")


# ======================================================================
# Incoming Data Generator
# ======================================================================
def render_incoming() -> None:
    page_header("Incoming Data Generator", "One click produces a batch of incoming records derived from the master data – with realistic variations.")
    how_it_works(
        "For **matching** records the generator takes a real master record and applies a variation: exact copy, spelling change, "
        "word-order change, phone format (`+91`, `0`, spaces, dashes), address abbreviation (*MG Road ↔ Mahatma Gandhi Road*), "
        "missing email, missing phone.\n\n"
        "**Noisy** records alternate between *conflicting email* (same person, new mailbox) and *general noise* (typos, corrupted phone, wrong PIN). "
        "**Ambiguous** records are sparse (name + city only) and have two look-alike master records. "
        "**No-match** records are brand-new people. **Duplicates** copy another record in the same batch.\n\n"
        "Because the generator knows the source record, it stores a **ground-truth label** for every row – this is what makes "
        "precision / recall measurable. Percentages must sum to 100."
    )
    with get_session() as session:
        counts = repo.counts_summary(session)
        batches = repo.list_batches(session)
    if counts["master"] == 0:
        st.warning("Generate master data first (Master Data page).")
        return
    st.caption(f"Master records available: **{counts['master']:,}**")

    with st.form("incoming_form"):
        c = st.columns(3)
        n = c[0].number_input("Number of incoming records", min_value=5, max_value=5000, value=100, step=5)
        seed = c[1].number_input("Random seed", min_value=0, value=7)
        run_now = c[2].checkbox("Run Search & Match immediately", value=True)
        c = st.columns(5)
        match = c[0].number_input("Expected Match %", 0.0, 100.0, 70.0, 1.0)
        no_match = c[1].number_input("Expected No Match %", 0.0, 100.0, 15.0, 1.0)
        noisy = c[2].number_input("Noisy Records %", 0.0, 100.0, 5.0, 1.0)
        ambiguous = c[3].number_input("Ambiguous Records %", 0.0, 100.0, 5.0, 1.0)
        duplicate = c[4].number_input("Duplicate Records %", 0.0, 100.0, 5.0, 1.0)
        total = match + no_match + noisy + ambiguous + duplicate
        store_gt = st.checkbox("Store ground-truth labels (recommended – enables precision/recall)", value=True)
        go = st.form_submit_button("🎲 GENERATE INCOMING DATA", type="primary")
    if abs(total - 100) > 0.01:
        st.error(f"Percentages must sum to 100% (currently {total:g}%).")
        go = False
    if go:
        cfg = get_active_config()
        with st.spinner("Generating incoming records…"):
            summary = generate_incoming_data(int(n), match, no_match, noisy, ambiguous, duplicate, seed=int(seed),
                                             store_ground_truth=store_gt, run_now=run_now)
        st.session_state["last_batch_id"] = summary.batch_id
        msg = f"Batch **{summary.batch_id}** created with {summary.records} records and {summary.ground_truth_labels} ground-truth labels."
        if summary.twins_added:
            msg += f" {summary.twins_added} look-alike master record(s) were added to support the ambiguous scenario."
        st.success(msg)
        if summary.run_id:
            with get_session() as session:
                run = repo.get_run(session, summary.run_id)
            st.session_state["selected_run_id"] = summary.run_id
            st.info(f"Run **{summary.run_id}** (algorithm v{cfg.version_name}): **{run.total_matches} MATCH · "
                    f"{run.total_manual_reviews} MANUAL_REVIEW · {run.total_no_matches} NO_MATCH** · HIT rate {run.hit_rate}% · "
                    f"precision {run.precision}% · recall {run.recall}%. Open *Match Results* to explore.")
        st.markdown("**Scenario mix of this batch**")
        sc = pd.DataFrame(sorted(summary.scenario_counts.items(), key=lambda kv: int(kv[0].split()[0][1:])), columns=["Scenario", "Records"])
        df(sc)

    st.subheader("Scenarios the generator can produce")
    df(pd.DataFrame({"Scenario": list(SCENARIO_LABELS.values()), "Category": [
        "Match", "Match", "Match", "Match", "Match", "Match", "Match", "Noisy", "Ambiguous", "No match", "Duplicate", "Noisy"]}))

    st.subheader("Existing batches")
    if batches.empty:
        st.info("No batches yet.")
    else:
        df(batches)
