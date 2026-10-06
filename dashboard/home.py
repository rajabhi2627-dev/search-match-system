"""Page 1 – Executive Dashboard (KPI cards, trends, RAG status, data quality)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard.common import df, get_active_config, how_it_works, kpi, page_header
from database import repository as repo
from database.database import get_session
from performance.metrics import GT_UNAVAILABLE, METRIC_DEFINITIONS
from performance.thresholds import rag_status
from utils.helpers import pct


def _latest_run(runs: pd.DataFrame) -> pd.Series | None:
    if runs.empty:
        return None
    return runs.sort_values(["timestamp", "run_id"]).iloc[-1]


def render() -> None:
    page_header("Executive Dashboard", "Search, Match & Merge – deterministic entity resolution with performance monitoring (Phase 1).")

    with get_session() as session:
        counts = repo.counts_summary(session)
        runs = repo.runs_frame(session)
        thresholds = {t.metric: t for t in repo.get_thresholds(session)}
    cfg = get_active_config()
    latest = _latest_run(runs)

    how_it_works(
        "This dashboard summarises the health of the matching engine.\n\n"
        "* **KPI cards** show the latest run. Metrics that need labelled data (precision, recall) say *n/a* until ground truth exists.\n"
        "* **Green / Amber / Red** indicators compare each metric with the prototype monitoring thresholds from the *Thresholds* page.\n"
        "* **Trend charts** show how performance changes from run to run and from algorithm version to version.\n\n"
        "Suggested demo flow: *Master Data → Incoming Data Generator → Match Results → Manual Review → Merge Review → "
        "Ground Truth → Algorithm Versions → Performance*."
    )

    # ------------------------------------------------------------ KPIs
    st.subheader("Key indicators" + (f" – latest run {latest['run_id']} (v{latest['algorithm_version']})" if latest is not None else ""))

    def status(metric: str, value):
        t = thresholds.get(metric)
        return rag_status(value, t.direction, t.green, t.amber) if t and value is not None else None

    row1 = st.columns(5)
    with row1[0]:
        kpi("Total master records", f"{counts['master']:,}")
    with row1[1]:
        kpi("Total incoming records", f"{counts['incoming']:,}")
    with row1[2]:
        kpi("Match rate", pct(latest["match_rate"]) if latest is not None else "n/a", METRIC_DEFINITIONS["match_rate"])
    with row1[3]:
        v = latest["hit_rate"] if latest is not None else None
        kpi("HIT rate", pct(v), METRIC_DEFINITIONS["hit_rate"], status("hit_rate", v))
    with row1[4]:
        kpi("Current algorithm version", f"v{cfg.version_name}", cfg.description or None)

    row2 = st.columns(5)
    gt_help = "Needs ground truth. " + GT_UNAVAILABLE
    with row2[0]:
        v = latest["precision"] if latest is not None else None
        kpi("Precision", pct(v), METRIC_DEFINITIONS["precision"] if v is not None else gt_help, status("precision", v))
    with row2[1]:
        v = latest["recall"] if latest is not None else None
        kpi("Recall", pct(v), METRIC_DEFINITIONS["recall"] if v is not None else gt_help, status("recall", v))
    with row2[2]:
        v = latest["manual_review_rate"] if latest is not None else None
        kpi("Manual review rate", pct(v), METRIC_DEFINITIONS["manual_review_rate"], status("manual_review_rate", v))
    with row2[3]:
        v = latest["dispute_rate"] if latest is not None else None
        kpi("Dispute rate", pct(v) if v is not None else "0.0%", METRIC_DEFINITIONS["dispute_rate"], status("dispute_rate", v if v is not None else 0.0))
    with row2[4]:
        v = latest["merge_error_rate"] if latest is not None else None
        kpi("Merge error rate", pct(v) if v is not None else "n/a", METRIC_DEFINITIONS["merge_error_rate"] + " n/a until merges exist.", status("merge_error_rate", v))

    if latest is not None and not latest["ground_truth_available"]:
        st.info(f"{GT_UNAVAILABLE} Load labels on the *Ground Truth* page (the Incoming Data Generator stores labels automatically).")

    if latest is None:
        st.warning("No matching run yet. Generate master data, then incoming data, and run Search & Match.")
        return

    # --------------------------------------------------------- overview
    c1, c2 = st.columns([1, 2])
    with c1:
        st.plotly_chart(charts.decision_distribution({
            "MATCH": int(latest["total_matches"]), "MANUAL_REVIEW": int(latest["total_manual_reviews"]),
            "NO_MATCH": int(latest["total_no_matches"])}, f"Latest run {latest['run_id']}"), width="stretch")
    with c2:
        st.plotly_chart(charts.decision_stacked_by_run(runs), width="stretch")

    # ------------------------------------------------------------ trends
    st.subheader("Performance trends")
    st.caption("Each point is one matching run. Colour = algorithm version. Dotted lines = Green / Amber monitoring thresholds.")
    metric_cards = [
        ("hit_rate", "1. HIT Rate over time"), ("precision", "2. Precision over time"), ("recall", "3. Recall over time"),
        ("f1_score", "4. F1 Score over time"), ("false_positive_rate", "5. False Positive Rate"),
        ("false_negative_rate", "6. False Negative Rate"), ("manual_review_rate", "7. Manual Review Rate"),
        ("dispute_rate", "8. Dispute Rate"), ("merge_error_rate", "9. Merge Error Rate"),
    ]
    for i in range(0, len(metric_cards), 3):
        cols = st.columns(3)
        for col, (metric, title) in zip(cols, metric_cards[i:i + 3]):
            t = thresholds.get(metric)
            with col:
                st.plotly_chart(charts.trend_chart(runs, metric, title, {"green": t.green, "amber": t.amber} if t else None), width="stretch")

    # ------------------------------------------------- version comparison
    st.subheader("11. Algorithm version comparison")
    versions = sorted(runs["algorithm_version"].dropna().unique().tolist())
    if len(versions) >= 2:
        from performance.version_comparison import aggregate_runs, compare_versions
        a, b = versions[-2], versions[-1]
        agg_a = aggregate_runs(runs[runs["algorithm_version"] == a].to_dict("records"))
        agg_b = aggregate_runs(runs[runs["algorithm_version"] == b].to_dict("records"))
        table = compare_versions(agg_a, agg_b, f"v{a}", f"v{b}")
        st.plotly_chart(charts.version_comparison_chart(table, f"v{a}", f"v{b}"), width="stretch")
        st.caption("Values are averaged over all runs of each version. Full detail on the *Performance → Algorithm Comparison* tab.")
    else:
        st.info("Create a second algorithm version (Algorithm Versions page) and re-run a batch to compare versions.")

    # ------------------------------------------------------ data quality
    st.subheader("Input data quality (latest run)")
    quality = latest["data_quality"] or {}
    if quality:
        q_cols = st.columns(7)
        labels = [("missing_name_pct", "Missing name"), ("missing_email_pct", "Missing email"), ("missing_phone_pct", "Missing phone"),
                  ("missing_address_pct", "Missing address"), ("duplicate_input_pct", "Duplicate input"),
                  ("invalid_email_pct", "Invalid email"), ("invalid_phone_pct", "Invalid phone")]
        for col, (key, label) in zip(q_cols, labels):
            col.metric(label, pct(quality.get(key)))
        st.caption("Poor input quality (many missing or invalid identifiers) weakens blocking and lowers scores – it often explains a low HIT rate.")
    else:
        st.caption("No data-quality profile stored for this run.")

    with st.expander("Run history (raw table)"):
        show = runs.drop(columns=["data_quality"]).sort_values("timestamp", ascending=False)
        df(show)
