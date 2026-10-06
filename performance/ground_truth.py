"""Ground-truth (golden dataset) handling.

A ground-truth file tells us, for each incoming record, which master entity
it REALLY belongs to.  Comparing the algorithm's output with these labels is
how precision, recall, F1, FPR and FNR are measured.

This module is only about measuring the matching algorithm – it is not an AI
validation framework.
"""
from __future__ import annotations

import pandas as pd

from data.excel_loader import read_table, standardize_columns
from performance.metrics import confusion_counts, metrics_from_counts
from utils.helpers import is_missing

REQUIRED = ["incoming_id", "true_entity_id", "true_decision"]
VALID_DECISIONS = {"MATCH", "NO_MATCH"}


def parse_ground_truth_file(file, filename: str | None = None) -> tuple[list[dict], list[str]]:
    """Read + validate a ground-truth file. Returns (rows, errors)."""
    df = read_table(file, filename)
    if df is None:
        return [], ["File could not be read. Use .xlsx or .csv."]
    if df.empty:
        return [], ["File is empty."]
    df, _ = standardize_columns(df)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}. Expected: {', '.join(REQUIRED)}."]
    rows, errors = [], []
    seen = set()
    for i, r in df.iterrows():
        iid = None if is_missing(r["incoming_id"]) else str(r["incoming_id"]).strip()
        if not iid:
            errors.append(f"Row {i + 2}: blank incoming_id.")
            continue
        if iid in seen:
            errors.append(f"Row {i + 2}: duplicate incoming_id {iid} – last value wins.")
        seen.add(iid)
        dec = "" if is_missing(r["true_decision"]) else str(r["true_decision"]).strip().upper().replace(" ", "_")
        ent = None if is_missing(r["true_entity_id"]) else str(r["true_entity_id"]).strip()
        if dec not in VALID_DECISIONS:
            # infer from entity id if possible
            dec = "MATCH" if ent else "NO_MATCH"
            errors.append(f"Row {i + 2}: true_decision not MATCH/NO_MATCH – inferred '{dec}'.")
        if dec == "MATCH" and not ent:
            errors.append(f"Row {i + 2}: MATCH without true_entity_id – row skipped.")
            continue
        rows.append({"incoming_id": iid, "true_entity_id": ent if dec == "MATCH" else None, "true_decision": dec})
    return rows, errors


def evaluate(results: list[dict], truth: dict[str, dict]) -> dict:
    """Confusion matrix + derived metrics for a list of result dicts."""
    cm = confusion_counts(results, truth)
    c = cm["counts"]
    metrics = metrics_from_counts(c["TP"], c["FP"], c["FN"], c["TN"])
    return {"counts": c, "metrics": metrics, "outcomes": cm["outcomes"]}


def confusion_matrix_frame(counts: dict) -> pd.DataFrame:
    """2×2 confusion matrix as a DataFrame (rows = predicted, cols = actual)."""
    return pd.DataFrame(
        [[counts["TP"], counts["FP"]], [counts["FN"], counts["TN"]]],
        index=["Predicted MATCH", "Predicted NO_MATCH"],
        columns=["Actual MATCH", "Actual NO_MATCH"],
    )


def outcome_table(results: list[dict], truth: dict[str, dict], outcomes: dict[str, str]) -> pd.DataFrame:
    rows = []
    for r in results:
        t = truth.get(r["incoming_id"], {})
        rows.append({
            "Incoming ID": r["incoming_id"],
            "Predicted Entity": r.get("entity_id") or "-",
            "Predicted Decision": r.get("decision"),
            "Score": r.get("overall_score"),
            "True Entity": t.get("true_entity_id") or "-",
            "True Decision": t.get("true_decision") or "-",
            "Outcome": outcomes.get(r["incoming_id"], "UNLABELLED"),
        })
    return pd.DataFrame(rows)
