"""Page 10 – Algorithm Versions (view history, create a new version, activate)."""
from __future__ import annotations

import streamlit as st

from dashboard.common import df, flash, how_it_works, page_header
from database import repository as repo
from database.database import get_session
from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BLOCKING_PASSES
from utils.helpers import MATCH_FIELDS


def render() -> None:
    page_header("Algorithm Versions", "Weights, thresholds and blocking rules are versioned. Changing any of them creates a NEW version – history is never overwritten.")
    how_it_works(
        "An algorithm version is the complete parameter set of the matcher: six **field weights** (must sum to 100), three "
        "**decision thresholds** (match, manual review, ambiguity gap), the enabled **blocking passes**, the **rare-value weighting** switch "
        "and **top-N**.\n\n"
        "Every run records the version it used, so results from v1.0 and v1.1 can be compared on the Performance page and tested "
        "for regressions. Only one version is *active* at a time – new runs use the active version."
    )
    with get_session() as session:
        versions = repo.list_versions(session)
        active = repo.get_active_version(session)
        table = repo.versions_frame(session)
        suggested = repo.next_version_name(session)
    active_cfg = AlgorithmConfig.from_db_row(active)

    st.subheader(f"Active version: v{active.version_name}")
    df(table)

    col1, col2 = st.columns([2, 1])
    with col2:
        st.markdown("**Activate an existing version**")
        pick = st.selectbox("Version", [v.version_name for v in versions], index=[v.version_name for v in versions].index(active.version_name))
        if st.button("Activate", disabled=(pick == active.version_name)):
            with get_session() as session:
                repo.activate_version(session, pick)
            st.cache_resource.clear()
            flash(f"v{pick} is now active.")
            st.rerun()

    with col1:
        st.subheader("Create a new version")
        st.caption(f"Pre-filled from the active version v{active.version_name}. Suggested name: v{suggested}.")
        with st.form("new_version"):
            name = st.text_input("Version name", value=suggested)
            st.markdown("**Field weights (%)** – must sum to 100")
            wcols = st.columns(6)
            weights = {}
            for col, f in zip(wcols, MATCH_FIELDS):
                weights[f] = col.number_input(f.upper() if f == "dob" else f.title(), 0.0, 100.0, float(active_cfg.weights[f]), 1.0, key=f"w_{f}")
            total = sum(weights.values())
            st.write(f"Total: **{total:g}%**" + ("" if abs(total - 100) < 0.01 else "  ⚠️ must be 100"))

            st.markdown("**Decision thresholds** (prototype settings, not regulatory requirements)")
            t1, t2, t3 = st.columns(3)
            match_t = t1.number_input("Match threshold (score ≥)", 0.0, 100.0, float(active_cfg.match_threshold), 1.0)
            review_t = t2.number_input("Manual review threshold (score ≥)", 0.0, 100.0, float(active_cfg.manual_review_threshold), 1.0)
            gap_t = t3.number_input("Ambiguity gap threshold (gap ≥)", 0.0, 50.0, float(active_cfg.ambiguity_gap_threshold), 0.5)

            st.markdown("**Blocking passes**")
            passes = st.multiselect("Enabled passes (order of execution)", list(BLOCKING_PASSES), default=active_cfg.blocking_passes,
                                    format_func=lambda p: BLOCKING_PASSES[p][0])
            o1, o2 = st.columns(2)
            rare = o1.toggle("Rare-value / information weighting", value=active_cfg.rare_value_weighting,
                             help="Multiplies weights by a capped factor (0.7–1.5) based on how rare the master value is.")
            top_n = o2.number_input("Top-N candidates", 1, 20, int(active_cfg.top_n))
            description = st.text_area("Description – what changed and why", placeholder="e.g. Increased phone weight, lowered ambiguity gap to 3")
            activate = st.checkbox("Activate immediately", value=True)
            submitted = st.form_submit_button("➕ CREATE VERSION", type="primary")
        if submitted:
            cfg = AlgorithmConfig(version_name=name.strip(), weights=weights, match_threshold=match_t, manual_review_threshold=review_t,
                                  ambiguity_gap_threshold=gap_t, blocking_passes=passes, rare_value_weighting=rare, top_n=int(top_n),
                                  description=description)
            problems = cfg.validate()
            if cfg.signature() == active_cfg.signature():
                problems.append("Nothing changed compared with the active version – a new version is only needed when weights, thresholds or blocking rules change.")
            if problems:
                for p in problems:
                    st.error(p)
            else:
                try:
                    with get_session() as session:
                        repo.create_version(session, cfg, description or "No description", activate=activate)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.cache_resource.clear()
                    flash(f"Version v{cfg.version_name} created{' and activated' if activate else ''}. "
                          "Next: re-run a batch (Match Results) and compare versions (Performance), or run a Regression Test.")
                    st.rerun()

    with st.expander("What changed between versions?"):
        if len(versions) < 2:
            st.caption("Only one version exists.")
        else:
            a = versions[-2]
            b = versions[-1]
            sa, sb = AlgorithmConfig.from_db_row(a).signature(), AlgorithmConfig.from_db_row(b).signature()
            rows = []
            for key in sa:
                if key == "weights":
                    for f in MATCH_FIELDS:
                        if sa["weights"][f] != sb["weights"][f]:
                            rows.append({"Parameter": f"weight.{f}", f"v{a.version_name}": sa["weights"][f], f"v{b.version_name}": sb["weights"][f]})
                elif sa[key] != sb[key]:
                    rows.append({"Parameter": key, f"v{a.version_name}": str(sa[key]), f"v{b.version_name}": str(sb[key])})
            if rows:
                import pandas as pd
                df(pd.DataFrame(rows))
            else:
                st.caption("No parameter differences.")
