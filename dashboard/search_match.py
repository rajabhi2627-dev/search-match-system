"""Page 2 – Search & Match (manual single-record search with full explanation)."""
from __future__ import annotations

import streamlit as st

from dashboard.common import get_active_config, get_index, how_it_works, outcome_to_view, page_header, render_outcome
from data.incoming_generator import worked_example_incoming
from database import repository as repo
from database.database import get_session
from matching.pipeline import MatchEngine

FIELDS = [("name", "Name"), ("email", "Email"), ("phone", "Phone"), ("address", "Address"), ("date_of_birth", "Date of birth (YYYY-MM-DD)"),
          ("company", "Company"), ("city", "City"), ("state", "State"), ("postal_code", "Postal code")]


def render() -> None:
    page_header("Search & Match", "Enter an incoming record and see exactly how the engine finds, scores and decides on candidates.")
    how_it_works(
        "1. **Normalization** – the values you type are lower-cased, punctuation is removed, phone digits are extracted, "
        "address abbreviations are standardised.\n"
        "2. **Blocking** – instead of comparing against every master record, the engine looks up candidates that share a key "
        "(phone, email, postal code + surname, city + surname, phonetic surname + city, first name + city).\n"
        "3. **Exact rules** then **fuzzy matching** (RapidFuzz: WRatio, Ratio, Token Sort, Token Set, Jaro-Winkler) score each field.\n"
        "4. **Weighted score** over the available fields → **conflict detection** → **top-5 ranking** → **score gap** → "
        "**confidence** → **decision**.\n\n"
        "Expand *Why did candidate #n …* under the results to see every intermediate number."
    )

    with get_session() as session:
        master_n = repo.master_count(session)
    if master_n == 0:
        st.warning("The master database is empty. Generate master data first (Master Data page).")
        return

    cfg = get_active_config()
    st.caption(f"Active algorithm version **v{cfg.version_name}** · match ≥ {cfg.match_threshold:g} · review ≥ {cfg.manual_review_threshold:g} · "
               f"gap ≥ {cfg.ambiguity_gap_threshold:g} · rare-value weighting {'ON' if cfg.rare_value_weighting else 'OFF'}")

    col_a, col_b = st.columns([1, 5])
    if col_a.button("Load worked example", help="RAHUL SHARMA / +91 9876543210 / 12 Mahatma Gandhi Road Patna"):
        for k, v in worked_example_incoming().items():
            st.session_state[f"search_{k}"] = v or ""
    if col_b.button("Clear form"):
        for k, _ in FIELDS:
            st.session_state[f"search_{k}"] = ""

    with st.form("search_form"):
        cols = st.columns(3)
        values = {}
        for i, (key, label) in enumerate(FIELDS):
            values[key] = cols[i % 3].text_input(label, key=f"search_{key}")
        submitted = st.form_submit_button("🔍 SEARCH & MATCH", type="primary")

    if not submitted and "search_last_outcome" not in st.session_state:
        return
    if submitted:
        record = {k: (v.strip() or None) for k, v in values.items()}
        if not any(record.values()):
            st.error("Enter at least one field.")
            return
        engine = MatchEngine(cfg, get_index())
        outcome = engine.match_record(record)
        st.session_state["search_last_outcome"] = outcome_to_view(outcome)
        with get_session() as session:
            repo.log_audit(session, "SEARCH", "user", record_ref=record.get("name"), algorithm_version=cfg.version_name,
                           new_value={"decision": outcome.decision, "entity_id": outcome.best_entity_id, "score": outcome.best_score})

    view = st.session_state["search_last_outcome"]
    st.divider()
    st.caption(f"Matched in {view.get('duration_ms', 0):.1f} ms with algorithm v{view['version']}.")
    render_outcome(view)
