"""Search, Match & Merge – Phase 1 prototype.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from dashboard import audit, batch_upload, generator, ground_truth, home, merge, methodology, performance, results, review, search_match, thresholds, versions
from dashboard.common import bootstrap
from database import repository as repo
from database.database import get_session
from utils.helpers import load_config

st.set_page_config(page_title="Search, Match & Merge", page_icon="🔎", layout="wide", initial_sidebar_state="expanded")

PAGES = {
    "1. Executive Dashboard": home.render,
    "2. Search & Match": search_match.render,
    "3. Batch Upload": batch_upload.render,
    "4. Incoming Data Generator": generator.render_incoming,
    "5. Master Data": generator.render_master,
    "6. Match Results": results.render,
    "7. Manual Review": review.render,
    "8. Merge Review": merge.render,
    "9. Performance": performance.render,
    "10. Algorithm Versions": versions.render,
    "11. Ground Truth": ground_truth.render,
    "12. Thresholds": thresholds.render,
    "13. Audit Log": audit.render,
    "14. Methodology": methodology.render,
}


def main() -> None:
    bootstrap()
    cfg = load_config()

    with st.sidebar:
        st.markdown(f"## 🔎 {cfg['app']['title']}")
        st.caption("Phase 1 · deterministic · explainable · rule-based")
        page = st.radio("Navigation", list(PAGES), label_visibility="collapsed")
        st.divider()
        with get_session() as session:
            counts = repo.counts_summary(session)
            active = repo.get_active_version(session)
        st.markdown(
            f"**Master records:** {counts['master']:,}  \n"
            f"**Incoming records:** {counts['incoming']:,}  \n"
            f"**Runs:** {counts['runs']} · **Labels:** {counts['ground_truth']:,}  \n"
            f"**Active algorithm:** v{active.version_name}"
        )
        st.divider()
        st.caption(cfg["app"]["synthetic_banner"])
        st.caption("No AI / LLM is used anywhere in this prototype.")

    PAGES[page]()


main()
