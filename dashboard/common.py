"""Shared Streamlit building blocks used by every page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from database import repository as repo
from database.database import get_session, init_db
from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BlockingIndex, pass_label
from matching.exact_match import exact_summary
from matching.preprocessing import normalization_table, normalize_record
from matching.scoring import calculation_rows
from matching.types import MatchOutcome
from utils.helpers import (
    MATCH_FIELDS, RECORD_FIELDS, FIELD_LABELS, confidence_emoji, decision_emoji, fmt_score, load_config, pct, rag_emoji,
)

FIELD_TITLES = {"name": "Name", "email": "Email", "phone": "Phone", "address": "Address", "dob": "DOB", "company": "Company"}


# ---------------------------------------------------------------- setup
def bootstrap() -> None:
    """Create tables + defaults once per session."""
    if not st.session_state.get("_bootstrapped"):
        init_db()
        with get_session() as session:
            repo.ensure_defaults(session)
            empty = repo.master_count(session) == 0
        if empty:
            _auto_seed()
        st.session_state["_bootstrapped"] = True


def _auto_seed() -> None:
    """Seed synthetic data on a fresh/empty database so a new deployment is not blank."""
    app_cfg = load_config().get("app", {})
    n_master = int(app_cfg.get("auto_seed_master", 0) or 0)
    n_incoming = int(app_cfg.get("auto_seed_incoming", 0) or 0)
    if n_master <= 0:
        return
    from workflows.runner import generate_incoming_data, generate_master_data   # local import: avoids import cycle

    with st.spinner(f"First start: seeding {n_master:,} synthetic master records…"):
        generate_master_data(n_master, actor="auto-seed")
        if n_incoming > 0:
            generate_incoming_data(n_incoming, match_pct=70, no_match_pct=15, noisy_pct=5, ambiguous_pct=5,
                                   duplicate_pct=5, run_now=True, actor="auto-seed")


@st.cache_resource(show_spinner="Building master index (blocking keys)…")
def _cached_index(fingerprint: tuple) -> BlockingIndex:
    with get_session() as session:
        records = repo.load_master_records(session)
    return BlockingIndex(records)


def get_index() -> BlockingIndex:
    """Blocking index of the current master data (rebuilt only when master data changes)."""
    with get_session() as session:
        fp = repo.master_fingerprint(session)
    return _cached_index(fp)


def get_active_config() -> AlgorithmConfig:
    with get_session() as session:
        return repo.get_active_config(session)


def synthetic_banner() -> None:
    st.caption(f"ℹ️ {load_config()['app']['synthetic_banner']}")


def flash(message: str, kind: str = "success") -> None:
    """Queue a message that survives the next st.rerun() (shown by page_header)."""
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        getattr(st, kind if kind in {"success", "warning", "error", "info"} else "info")(message)


def page_header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    if subtitle:
        st.markdown(subtitle)
    synthetic_banner()
    show_flash()


def how_it_works(markdown: str, expanded: bool = False) -> None:
    with st.expander("❓ How does this work?", expanded=expanded):
        st.markdown(markdown)


def kpi(label: str, value, help_text: str | None = None, status: str | None = None, delta=None) -> None:
    prefix = f"{rag_emoji(status)} " if status else ""
    st.metric(f"{prefix}{label}", value, delta=delta, help=help_text)


def gt_unavailable_value(value: float | None) -> str:
    return pct(value) if value is not None else "n/a"


def decision_badge(decision: str | None) -> str:
    return f"{decision_emoji(decision)} {decision or '-'}"


def confidence_badge(level: str | None) -> str:
    return f"{confidence_emoji(level)} {level or '-'}"


def record_frame(record: dict, title: str = "Value") -> pd.DataFrame:
    return pd.DataFrame({"Field": [FIELD_LABELS[f] for f in RECORD_FIELDS], title: [record.get(f) or "" for f in RECORD_FIELDS]})


def df(data: pd.DataFrame, **kwargs) -> None:
    """st.dataframe with sensible defaults."""
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("width", "stretch")
    st.dataframe(data, **kwargs)


# ======================================================================
# Explanation view model – works for live outcomes AND stored results
# ======================================================================
def outcome_to_view(outcome: MatchOutcome) -> dict:
    return {
        "incoming": outcome.incoming,
        "normalized": outcome.normalized,
        "pool_size": outcome.pool_size,
        "master_size": outcome.master_size,
        "reduction_pct": outcome.reduction_pct,
        "decision": outcome.decision,
        "decision_rule": outcome.decision_rule,
        "reason": outcome.reason,
        "confidence": outcome.confidence,
        "confidence_points": outcome.confidence_points,
        "confidence_factors": outcome.confidence_factors,
        "score_gap": outcome.score_gap,
        "set_conflicts": outcome.set_conflicts,
        "blocking_passes": outcome.blocking_passes_used,
        "version": outcome.algorithm_version,
        "duration_ms": outcome.duration_ms,
        "candidates": [c.to_dict() for c in outcome.candidates],
    }


def stored_to_view(result: dict, candidates: list[dict], incoming: dict) -> dict:
    details = result.get("details", {}) or {}
    return {
        "incoming": incoming,
        "normalized": normalize_record(incoming),
        "pool_size": result.get("candidate_pool_size"),
        "master_size": result.get("master_size"),
        "reduction_pct": (round((1 - result["candidate_pool_size"] / result["master_size"]) * 100, 2)
                          if result.get("master_size") and result.get("candidate_pool_size") is not None else None),
        "decision": result["decision"],
        "decision_rule": result.get("decision_rule"),
        "reason": result.get("reason"),
        "confidence": result.get("confidence"),
        "confidence_points": details.get("confidence_points"),
        "confidence_factors": details.get("confidence_factors", []),
        "score_gap": result.get("score_gap"),
        "set_conflicts": details.get("set_conflicts", []),
        "blocking_passes": details.get("blocking_passes", []),
        "version": result.get("algorithm_version"),
        "duration_ms": details.get("duration_ms"),
        "candidates": candidates,
    }


def candidate_table(view: dict) -> pd.DataFrame:
    rows = []
    for c in view["candidates"]:
        fs = c["field_scores"]
        rows.append({
            "Rank": c["rank"],
            "Entity ID": c["entity_id"],
            "Name": (c.get("master") or {}).get("name", ""),
            "Overall": c["overall"],
            **{FIELD_TITLES[f]: fs.get(f) for f in MATCH_FIELDS},
            "Confidence": c.get("confidence"),
            "Conflict": "Yes" if (c.get("conflict_flag") or c.get("conflicts")) else "No",
            "Decision if best": c.get("decision"),
            "Blocking": ", ".join(pass_label(p).split(" – ")[0] for p in c.get("blocking_methods", [])),
        })
    return pd.DataFrame(rows)


def render_summary_strip(view: dict) -> None:
    best = view["candidates"][0] if view["candidates"] else None
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Decision", view["decision"])
    c2.metric("Best candidate", best["entity_id"] if best else "-")
    c3.metric("Overall score", fmt_score(best["overall"]) if best else "-")
    c4.metric("Score gap", fmt_score(view["score_gap"]))
    c5.metric("Confidence", f"{view['confidence']} ({view.get('confidence_points', '-')} pts)")
    conflicts = (best.get("conflicts", []) if best else []) + view.get("set_conflicts", [])
    c6.metric("Conflict", f"{len(conflicts)} found" if conflicts else "None")


def render_blocking_metrics(view: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Master records", f"{view['master_size']:,}" if view["master_size"] is not None else "-")
    c2.metric("Candidates before blocking", f"{view['master_size']:,}" if view["master_size"] is not None else "-")
    c3.metric("Candidates after blocking", f"{view['pool_size']:,}" if view["pool_size"] is not None else "-")
    c4.metric("Candidate reduction", pct(view["reduction_pct"], 2))


def render_candidate_explanation(view: dict, cand: dict, weights: dict | None = None) -> None:
    """Full 'Why did this candidate match?' panel for ONE candidate."""
    master = cand.get("master") or {}
    fs = cand["field_scores"]
    details = cand.get("field_details", {})
    breakdown = cand.get("breakdown", {})
    conflicts = list(cand.get("conflicts", []))
    if cand["rank"] == 1:
        conflicts += view.get("set_conflicts", [])

    st.markdown("**1. Normalization** – original vs normalized values of both records")
    inc_rows = normalization_table(view["normalized"])
    mas_rows = normalization_table(normalize_record(master))
    norm_df = pd.DataFrame({
        "Field": [r["Field"] for r in inc_rows],
        "Incoming (original)": [r["Original"] for r in inc_rows],
        "Incoming (normalized)": [r["Normalized"] for r in inc_rows],
        "Master (original)": [r["Original"] for r in mas_rows],
        "Master (normalized)": [r["Normalized"] for r in mas_rows],
    })
    df(norm_df)

    st.markdown("**2. Blocking** – which passes produced this candidate")
    methods = cand.get("blocking_methods", [])
    st.write(" **AND** ".join(f"`{pass_label(p)}`" for p in methods) if methods else "—")

    st.markdown("**3. Exact matching rules**")
    st.write(exact_summary(cand.get("exact_rules", [])))

    st.markdown("**4. Field-level similarity** – multiple algorithms per field")
    rows = []
    for f in MATCH_FIELDS:
        d = details.get(f, {})
        sub = {k: v for k, v in d.items() if k not in ("score", "incoming", "master", "blend", "reason", "method")}
        rows.append({
            "Field": FIELD_TITLES[f],
            "Incoming": d.get("incoming") or "",
            "Master": d.get("master") or "",
            "Score": "not scored (missing)" if fs.get(f) is None else f"{fs[f]:.1f}",
            "Method / sub-metrics": (d.get("method") + "; " if d.get("method") else "") + ", ".join(f"{k}={v:.0f}" for k, v in sub.items() if isinstance(v, (int, float))),
        })
    df(pd.DataFrame(rows))

    st.markdown("**5. Weighted overall score** – the full calculation")
    if breakdown:
        df(pd.DataFrame(calculation_rows(breakdown, fs)))
        if breakdown.get("missing_fields"):
            st.caption(f"Missing fields ({', '.join(FIELD_TITLES[f] for f in breakdown['missing_fields'])}) are NOT scored as 0 – "
                       "their weight is removed and the remaining weights are re-normalized to 100%.")
        if any(v != 1.0 for v in breakdown.get("information_factors", {}).values()):
            st.caption("Rare-value weighting is ON: configured weights were multiplied by an information factor "
                       "(capped) based on how common the master value is, then re-normalized.")

    st.markdown("**6. Conflict detection**")
    if conflicts:
        for c in conflicts:
            (st.error if c["severity"] == "CRITICAL" else st.warning)(f"[{c['severity']}] {c['message']}")
    else:
        st.success("No conflicting fields detected.")

    st.markdown("**7. Ranking & score gap**")
    n = len(view["candidates"])
    gap = view["score_gap"] if cand["rank"] == 1 else cand.get("gap_to_next")
    st.write(f"Candidate rank **#{cand['rank']} of {n}**. "
             + (f"Score gap to second-best: **{fmt_score(view['score_gap'])}**." if cand["rank"] == 1 else f"Gap to next candidate: {fmt_score(gap)}."))

    st.markdown("**8. Confidence** – independent point system")
    factors = cand.get("confidence_factors") or []
    if factors:
        df(pd.DataFrame(factors).rename(columns={"factor": "Factor", "points": "Points", "detail": "Detail"}))
    st.write(f"Total **{cand.get('confidence_points', '-')} points → {cand.get('confidence', '-')}** "
             "(HIGH ≥ 70, MEDIUM ≥ 45, otherwise LOW).")

    if cand["rank"] == 1:
        st.markdown("**9. Decision rule**")
        st.info(view["reason"])


def render_outcome(view: dict, show_blocking_metrics: bool = True) -> None:
    """Standard explanation block: summary → candidates → per-candidate expanders."""
    render_summary_strip(view)
    if show_blocking_metrics:
        render_blocking_metrics(view)
    st.markdown("#### Top candidates")
    if not view["candidates"]:
        st.warning("No candidates were produced by blocking – no master record shares a phone, email, postal code + surname, "
                   "city + surname, phonetic surname or first-name key with this record.")
        st.info(view["reason"])
        return
    df(candidate_table(view), column_config={
        "Overall": st.column_config.ProgressColumn("Overall", min_value=0, max_value=100, format="%.1f"),
    })
    st.markdown("#### Explanation")
    st.info(view["reason"])
    for cand in view["candidates"]:
        label = f"Why did candidate #{cand['rank']} ({cand['entity_id']} – {(cand.get('master') or {}).get('name', '')}) score {cand['overall']:.1f}?"
        with st.expander(label, expanded=(cand["rank"] == 1 and len(view["candidates"]) == 1)):
            render_candidate_explanation(view, cand)


def decision_filter(options_key: str = "decision_filter") -> list[str]:
    return st.multiselect("Decision", ["MATCH", "MANUAL_REVIEW", "NO_MATCH"], default=["MATCH", "MANUAL_REVIEW", "NO_MATCH"], key=options_key)
