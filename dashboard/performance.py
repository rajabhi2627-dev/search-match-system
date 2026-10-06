"""Page 9 – Performance (run history, trends, algorithm comparison, regression test, stability test)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard.common import df, flash, get_index, how_it_works, page_header
from database import repository as repo
from database.database import get_session
from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BlockingIndex
from matching.pipeline import MatchEngine
from performance.metrics import GT_UNAVAILABLE, METRIC_DEFINITIONS
from performance.regression import run_regression, stability_test
from performance.version_comparison import COMPARISON_METRICS, aggregate_runs, compare_versions
from utils.helpers import load_config, pct


def render() -> None:
    page_header("Performance", "Every matching run is tracked. Compare runs, versions, and test for regressions and stability.")
    how_it_works(
        "**Always available:** Match Rate, HIT Rate, Manual Review Rate, Dispute Rate, Merge Error Rate, candidate reduction.\n\n"
        "**Only with ground truth:** Precision, Recall, F1, FPR, FNR, Accuracy – otherwise the UI says "
        f"*{GT_UNAVAILABLE}*\n\n"
        "**HIT Rate vs Precision** – HIT Rate asks *did the search find an acceptable candidate?* (best score ≥ review threshold). "
        "Precision asks *of the records we automatically matched, how many were right?* A system can have a high HIT rate and poor "
        "precision (it finds candidates but picks wrong ones) or the reverse.\n\n"
        "**Regression test** runs the same labelled data through two versions and flags material degradation "
        "(deterministic rule, configurable in percentage points). **Stability test** runs identical input several times – "
        "a deterministic engine must return identical results."
    )
    with get_session() as session:
        runs = repo.runs_frame(session)
        versions = repo.list_versions(session)
        thresholds = {t.metric: t for t in repo.get_thresholds(session)}
    if runs.empty:
        st.warning("No matching run yet.")
        return

    tab_runs, tab_cmp, tab_reg, tab_stab, tab_defs = st.tabs(["Runs & Trends", "Algorithm Comparison", "Regression Test", "Stability Test", "Metric Definitions"])

    # ------------------------------------------------------------- runs
    with tab_runs:
        st.subheader("Run history")
        table = runs.drop(columns=["data_quality"]).sort_values(["timestamp", "run_id"], ascending=False)
        pretty = table.rename(columns={
            "run_id": "Run", "batch_id": "Batch", "algorithm_version": "Version", "timestamp": "Time", "run_type": "Type",
            "total_records": "Records", "total_matches": "MATCH", "total_manual_reviews": "REVIEW", "total_no_matches": "NO_MATCH",
            "match_rate": "Match %", "hit_rate": "HIT %", "precision": "Precision %", "recall": "Recall %", "f1_score": "F1 %",
            "accuracy": "Accuracy %", "false_positive_rate": "FPR %", "false_negative_rate": "FNR %", "manual_review_rate": "Review %",
            "dispute_rate": "Dispute %", "merge_error_rate": "Merge err %", "candidate_reduction_pct": "Cand. reduction %",
            "avg_candidates": "Avg cands", "ground_truth_available": "GT?", "duration_ms": "ms",
        })
        df(pretty[["Run", "Batch", "Version", "Time", "Type", "Records", "MATCH", "REVIEW", "NO_MATCH", "Match %", "HIT %", "Precision %",
                   "Recall %", "F1 %", "FPR %", "FNR %", "Review %", "Dispute %", "Merge err %", "Cand. reduction %", "Avg cands", "GT?", "tp", "fp", "fn", "tn", "ms"]])
        if not runs["ground_truth_available"].all():
            st.info(GT_UNAVAILABLE + " Runs without labels show blanks for precision / recall / F1 / FPR / FNR.")
        if st.button("🔄 Recompute all run metrics (after loading ground truth or reviewing)"):
            with get_session() as session:
                n = repo.recompute_all_runs(session)
            flash(f"Recomputed {n} runs.")
            st.rerun()

        st.subheader("Trends")
        metrics = [("hit_rate", "HIT Rate"), ("precision", "Precision"), ("recall", "Recall"), ("f1_score", "F1 Score"),
                   ("false_positive_rate", "False Positive Rate"), ("false_negative_rate", "False Negative Rate"),
                   ("manual_review_rate", "Manual Review Rate"), ("dispute_rate", "Dispute Rate"), ("merge_error_rate", "Merge Error Rate"),
                   ("match_rate", "Match Rate"), ("candidate_reduction_pct", "Candidate Reduction %")]
        for i in range(0, len(metrics), 3):
            cols = st.columns(3)
            for col, (m, title) in zip(cols, metrics[i:i + 3]):
                t = thresholds.get(m)
                with col:
                    st.plotly_chart(charts.trend_chart(runs, m, title, {"green": t.green, "amber": t.amber} if t else None), width="stretch")
        st.plotly_chart(charts.decision_stacked_by_run(runs), width="stretch")

    # ------------------------------------------------------- comparison
    with tab_cmp:
        st.subheader("Algorithm Comparison")
        names = [v.version_name for v in versions]
        with_runs = sorted(runs["algorithm_version"].dropna().unique().tolist())
        if len(with_runs) < 2:
            st.info("At least two algorithm versions need runs before they can be compared. Create v1.1 on the Algorithm Versions "
                    "page and re-run a batch from Match Results.")
        else:
            c1, c2, c3 = st.columns(3)
            a = c1.selectbox("Version A (baseline)", with_runs, index=max(0, len(with_runs) - 2))
            b = c2.selectbox("Version B", with_runs, index=len(with_runs) - 1)
            batches = ["All batches"] + sorted(runs["batch_id"].dropna().unique().tolist())
            batch = c3.selectbox("Restrict to batch", batches, help="Compare like with like: pick a batch that was run under both versions.")
            sub = runs if batch == "All batches" else runs[runs["batch_id"] == batch]
            ra = sub[sub["algorithm_version"] == a].to_dict("records")
            rb = sub[sub["algorithm_version"] == b].to_dict("records")
            if not ra or not rb:
                st.warning("One of the versions has no run for this batch.")
            else:
                agg_a, agg_b = aggregate_runs(ra), aggregate_runs(rb)
                material = float(load_config().get("regression", {}).get("material_change_pp", 2.0))
                table = compare_versions(agg_a, agg_b, f"v{a}", f"v{b}", material_pp=0.0)
                st.caption(f"v{a}: {agg_a['runs']} run(s) · v{b}: {agg_b['runs']} run(s). Values averaged per version.")

                def colour(val):
                    return {"Improvement": "color: #2e7d32; font-weight: bold", "Degradation": "color: #c62828; font-weight: bold"}.get(val, "")
                show = table.drop(columns=["_key", "Definition"])
                st.dataframe(show.style.map(colour, subset=["Verdict"]), hide_index=True, width="stretch")
                st.plotly_chart(charts.version_comparison_chart(table, f"v{a}", f"v{b}"), width="stretch")
                for _, r in table.iterrows():
                    if r["Change (pp)"] is not None and r["Verdict"] in ("Improvement", "Degradation"):
                        sign = "+" if r["Change (pp)"] > 0 else ""
                        st.write(f"- **{r['Metric']}**: v{a} = {r[f'v{a}']:.1f}% → v{b} = {r[f'v{b}']:.1f}% ⇒ {r['Verdict']} ({sign}{r['Change (pp)']:.1f} percentage points)")

    # ------------------------------------------------------- regression
    with tab_reg:
        st.subheader("Regression Test (rule-based)")
        st.caption("Runs the SAME golden dataset through two algorithm versions in memory (nothing is stored) and compares the metrics.")
        if len(versions) < 2:
            st.info("Create a second algorithm version first.")
        else:
            names = [v.version_name for v in versions]
            c1, c2, c3 = st.columns(3)
            base = c1.selectbox("Baseline version", names, index=max(0, len(names) - 2), key="reg_base")
            cand = c2.selectbox("Candidate version", names, index=len(names) - 1, key="reg_cand")
            with get_session() as session:
                batches = repo.list_batches(session)
            batch = c3.selectbox("Golden dataset (batch)", batches["batch_id"].tolist(), key="reg_batch")
            material = st.slider("Material change threshold (percentage points)", 0.5, 10.0,
                                 float(load_config().get("regression", {}).get("material_change_pp", 2.0)), 0.5)
            if st.button("🧪 Run regression test", type="primary"):
                with get_session() as session:
                    records = repo.get_incoming_by_batch(session, batch)
                    truth = repo.get_ground_truth(session, [r["incoming_id"] for r in records])
                    cfg_a = AlgorithmConfig.from_db_row(repo.get_version(session, base))
                    cfg_b = AlgorithmConfig.from_db_row(repo.get_version(session, cand))
                with st.spinner("Running both versions…"):
                    report = run_regression(cfg_a, cfg_b, get_index(), records, truth or None, material_pp=material)
                with get_session() as session:
                    repo.log_audit(session, "REGRESSION_TEST", "user", record_ref=batch, algorithm_version=cand,
                                   old_value=base, new_value=cand, details=report.verdict)
                (st.error if report.regression_detected else st.success)(f"**{report.verdict}**")
                st.write(f"Records tested: {report.records_tested} · ground truth: {'available' if report.ground_truth_available else 'NOT available (only label-free metrics compared)'} · "
                         f"decisions that changed between versions: {report.changed_decisions}")
                if report.degraded:
                    st.write("Degraded: " + ", ".join(f"**{m}**" for m in report.degraded))
                if report.improved:
                    st.write("Improved: " + ", ".join(f"**{m}**" for m in report.improved))
                df(report.table.drop(columns=["_key", "Definition"]))
                if report.changed_rows is not None:
                    with st.expander(f"Records whose decision or entity changed ({report.changed_decisions})"):
                        df(report.changed_rows)

    # -------------------------------------------------------- stability
    with tab_stab:
        st.subheader("Stability Test")
        st.caption("Runs identical input N times. The engine is deterministic, so candidate, score and decision must be identical every time.")
        with get_session() as session:
            batches = repo.list_batches(session)
        c1, c2, c3 = st.columns(3)
        batch = c1.selectbox("Batch", batches["batch_id"].tolist(), key="stab_batch")
        n_runs = c2.number_input("Repetitions", 2, 20, 5)
        version = c3.selectbox("Version", [v.version_name for v in versions], index=len(versions) - 1, key="stab_version")
        if st.button("🔁 Run stability test", type="primary"):
            with get_session() as session:
                records = repo.get_incoming_by_batch(session, batch)
                cfg = AlgorithmConfig.from_db_row(repo.get_version(session, version))
            engine = MatchEngine(cfg, get_index())
            with st.spinner("Running…"):
                report = stability_test(engine, records, runs=int(n_runs))
            with get_session() as session:
                repo.log_audit(session, "STABILITY_TEST", "user", record_ref=batch, algorithm_version=version, details=report.verdict)
            (st.success if report.stable else st.error)(f"**{report.verdict}** – {report.records} records × {report.runs} runs")
            if not report.stable:
                df(pd.DataFrame(report.differences))

    # ------------------------------------------------------ definitions
    with tab_defs:
        st.subheader("Metric definitions (plain language)")
        df(pd.DataFrame([{"Metric": k.replace("_", " ").title(), "Definition": v} for k, v in METRIC_DEFINITIONS.items()]))
        st.markdown(
            "**Formulas**\n\n"
            "- Match Rate = MATCH / total\n"
            "- HIT Rate = records with best score ≥ manual-review threshold / total\n"
            "- Precision = TP / (TP + FP) · Recall = TP / (TP + FN) · F1 = 2·P·R / (P + R)\n"
            "- FPR = FP / (FP + TN) · FNR = FN / (FN + TP) · Accuracy = (TP + TN) / (TP + FP + FN + TN)\n"
            "- Manual Review Rate = MANUAL_REVIEW / total\n"
            "- Dispute Rate = disputed matches / total MATCH decisions\n"
            "- Merge Error Rate = incorrect merges / confirmed merges\n\n"
            "MANUAL_REVIEW records are excluded from TP/FP/FN/TN because no automatic decision was taken."
        )
