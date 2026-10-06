"""Compare the performance of two algorithm versions metric by metric.

Each metric is tagged with a direction (higher or lower is better) so the
comparison can say "Improvement" or "Degradation" in percentage points.
"""
from __future__ import annotations

import pandas as pd

from performance.metrics import HIGHER_IS_BETTER, METRIC_DEFINITIONS

COMPARISON_METRICS = [
    ("hit_rate", "HIT Rate"),
    ("precision", "Precision"),
    ("recall", "Recall"),
    ("f1_score", "F1 Score"),
    ("false_positive_rate", "False Positive Rate"),
    ("false_negative_rate", "False Negative Rate"),
    ("manual_review_rate", "Manual Review Rate"),
    ("match_rate", "Match Rate"),
    ("dispute_rate", "Dispute Rate"),
    ("merge_error_rate", "Merge Error Rate"),
]


def aggregate_runs(runs: list[dict]) -> dict[str, float | None]:
    """Average each metric over several runs of the same version (ignoring None)."""
    agg: dict[str, float | None] = {}
    for key, _ in COMPARISON_METRICS:
        values = [r.get(key) for r in runs if r.get(key) is not None]
        agg[key] = round(sum(values) / len(values), 2) if values else None
    agg["runs"] = len(runs)
    return agg


def verdict(metric: str, delta: float | None, material_pp: float = 0.0) -> str:
    if delta is None:
        return "Not available"
    direction = HIGHER_IS_BETTER.get(metric)
    if abs(delta) <= material_pp:
        return "No material change"
    if direction is None:
        return "Changed"
    improved = delta > 0 if direction else delta < 0
    return "Improvement" if improved else "Degradation"


def compare_versions(metrics_a: dict, metrics_b: dict, label_a: str, label_b: str,
                     material_pp: float = 0.0) -> pd.DataFrame:
    rows = []
    for key, label in COMPARISON_METRICS:
        a, b = metrics_a.get(key), metrics_b.get(key)
        delta = round(b - a, 2) if a is not None and b is not None else None
        rows.append({
            "Metric": label,
            label_a: a,
            label_b: b,
            "Change (pp)": delta,
            "Verdict": verdict(key, delta, material_pp),
            "Definition": METRIC_DEFINITIONS.get(key, ""),
            "_key": key,
        })
    return pd.DataFrame(rows)
