"""Plotly chart helpers (kept separate so pages stay readable)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

DECISION_COLOURS = {"MATCH": "#2e7d32", "MANUAL_REVIEW": "#f9a825", "NO_MATCH": "#c62828"}
RAG_COLOURS = {"GREEN": "#2e7d32", "AMBER": "#f9a825", "RED": "#c62828"}


def trend_chart(runs: pd.DataFrame, metric: str, title: str, thresholds: dict | None = None) -> go.Figure:
    """Metric over runs, coloured by algorithm version, with optional Green/Amber lines."""
    data = runs.dropna(subset=[metric]) if metric in runs.columns else pd.DataFrame()
    if data.empty:
        fig = go.Figure()
        fig.add_annotation(text="Ground truth unavailable — metric not calculated." if metric in (
            "precision", "recall", "f1_score", "false_positive_rate", "false_negative_rate") else "No data yet",
            showarrow=False, font={"size": 13, "color": "#757575"})
        fig.update_layout(title=title, height=260, margin={"l": 20, "r": 20, "t": 50, "b": 20},
                          xaxis={"visible": False}, yaxis={"visible": False})
        return fig
    data = data.copy()
    data["label"] = data["run_id"] + " (v" + data["algorithm_version"].astype(str) + ")"
    fig = px.line(data, x="label", y=metric, color="algorithm_version", markers=True, title=title,
                  labels={"label": "Run", metric: "%", "algorithm_version": "Version"})
    fig.update_traces(line={"width": 2.5}, marker={"size": 9})
    if thresholds:
        fig.add_hline(y=thresholds["green"], line={"color": RAG_COLOURS["GREEN"], "dash": "dot"}, annotation_text="Green")
        fig.add_hline(y=thresholds["amber"], line={"color": RAG_COLOURS["AMBER"], "dash": "dot"}, annotation_text="Amber")
    fig.update_layout(height=280, margin={"l": 20, "r": 20, "t": 50, "b": 20}, yaxis={"range": [0, 105]},
                      legend={"orientation": "h", "y": -0.3})
    return fig


def decision_distribution(counts: dict[str, int], title: str = "Decision distribution") -> go.Figure:
    labels = [k for k in ("MATCH", "MANUAL_REVIEW", "NO_MATCH") if counts.get(k)]
    values = [counts[k] for k in labels]
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.5,
                           marker={"colors": [DECISION_COLOURS[k] for k in labels]}, textinfo="label+value+percent"))
    fig.update_layout(title=title, height=320, margin={"l": 20, "r": 20, "t": 50, "b": 20}, showlegend=False)
    return fig


def decision_stacked_by_run(runs: pd.DataFrame) -> go.Figure:
    melted = runs.melt(id_vars=["run_id"], value_vars=["total_matches", "total_manual_reviews", "total_no_matches"],
                       var_name="decision", value_name="count")
    melted["decision"] = melted["decision"].map({"total_matches": "MATCH", "total_manual_reviews": "MANUAL_REVIEW", "total_no_matches": "NO_MATCH"})
    fig = px.bar(melted, x="run_id", y="count", color="decision", color_discrete_map=DECISION_COLOURS,
                 title="MATCH / MANUAL REVIEW / NO MATCH per run", labels={"run_id": "Run", "count": "Records"})
    fig.update_layout(height=320, margin={"l": 20, "r": 20, "t": 50, "b": 20}, legend={"orientation": "h", "y": -0.3})
    return fig


def version_comparison_chart(table: pd.DataFrame, label_a: str, label_b: str) -> go.Figure:
    data = table.dropna(subset=[label_a, label_b])
    fig = go.Figure()
    fig.add_bar(name=label_a, x=data["Metric"], y=data[label_a], marker_color="#90a4ae")
    fig.add_bar(name=label_b, x=data["Metric"], y=data[label_b], marker_color="#1565c0")
    fig.update_layout(barmode="group", title=f"{label_a} vs {label_b}", height=360, yaxis={"title": "%", "range": [0, 105]},
                      margin={"l": 20, "r": 20, "t": 50, "b": 20}, legend={"orientation": "h", "y": -0.25})
    return fig


def confusion_heatmap(cm: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Heatmap(z=cm.values, x=list(cm.columns), y=list(cm.index), text=cm.values, texttemplate="%{text}",
                               colorscale="Blues", showscale=False))
    fig.update_layout(title="Confusion matrix (automatic decisions only)", height=320, margin={"l": 20, "r": 20, "t": 50, "b": 20})
    return fig


def score_histogram(scores: pd.Series, match_threshold: float, review_threshold: float) -> go.Figure:
    fig = px.histogram(scores.dropna(), nbins=25, title="Best-candidate score distribution", labels={"value": "Overall score"})
    fig.add_vline(x=match_threshold, line={"color": DECISION_COLOURS["MATCH"], "dash": "dash"}, annotation_text="Match")
    fig.add_vline(x=review_threshold, line={"color": DECISION_COLOURS["MANUAL_REVIEW"], "dash": "dash"}, annotation_text="Review")
    fig.update_layout(height=300, margin={"l": 20, "r": 20, "t": 50, "b": 20}, showlegend=False)
    return fig


def field_score_bars(field_scores: dict[str, float | None]) -> go.Figure:
    labels = [k.upper() if k == "dob" else k.title() for k, v in field_scores.items() if v is not None]
    values = [v for v in field_scores.values() if v is not None]
    colours = ["#2e7d32" if v >= 90 else "#f9a825" if v >= 65 else "#c62828" for v in values]
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colours, text=[f"{v:.0f}" for v in values], textposition="outside"))
    fig.update_layout(height=260, yaxis={"range": [0, 110]}, margin={"l": 20, "r": 20, "t": 20, "b": 20})
    return fig
