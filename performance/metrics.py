"""STEP 14 – Performance metrics.

Two groups of metrics:

ALWAYS AVAILABLE (no labels needed)
    Match Rate          = MATCH decisions / total records
    HIT Rate            = records whose best candidate score >= manual-review
                          threshold (an "acceptable candidate" was found) / total
    Manual Review Rate  = MANUAL_REVIEW decisions / total
    Dispute Rate        = disputed matches / total MATCH decisions
    Merge Error Rate    = incorrect merges / confirmed merges

ONLY WITH GROUND TRUTH (labelled data)
    TP  predicted MATCH to the correct entity
    FP  predicted MATCH but the truth is NO_MATCH or a different entity
    FN  truth is MATCH but predicted NO_MATCH
    TN  predicted NO_MATCH and truth is NO_MATCH
    Precision = TP/(TP+FP)   Recall = TP/(TP+FN)   F1 = 2PR/(P+R)
    FPR = FP/(FP+TN)         FNR = FN/(FN+TP)      Accuracy = (TP+TN)/(all)

MANUAL_REVIEW records are *deferred* decisions.  They are excluded from the
confusion matrix (a human decides later) and reported through the Manual
Review Rate instead.  This keeps precision/recall about AUTOMATIC decisions.

If ground truth is unavailable the metric value is None and the UI prints
"Ground truth unavailable — metric not calculated."
"""
from __future__ import annotations

from utils.helpers import safe_div

GT_UNAVAILABLE = "Ground truth unavailable — metric not calculated."

METRIC_DEFINITIONS: dict[str, str] = {
    "match_rate": "Share of incoming records that received an automatic MATCH decision.",
    "hit_rate": "Share of incoming records for which the search found at least one acceptable candidate "
                "(best score ≥ manual-review threshold). It measures whether the SEARCH is finding candidates – "
                "not whether the candidate is correct.",
    "manual_review_rate": "Share of incoming records routed to a human reviewer.",
    "precision": "Of all automatic MATCH decisions, how many were correct (needs ground truth).",
    "recall": "Of all records that truly belong to a master entity, how many were automatically matched to the right entity (needs ground truth).",
    "f1_score": "Harmonic mean of precision and recall – a single balanced number.",
    "false_positive_rate": "Share of true NO_MATCH records that were wrongly matched (FP / (FP + TN)).",
    "false_negative_rate": "Share of true MATCH records that were missed (FN / (FN + TP)).",
    "accuracy": "Share of automatic decisions that were correct ((TP + TN) / all).",
    "dispute_rate": "Share of MATCH decisions later disputed by a human (rejected, re-assigned or merge reversed).",
    "merge_error_rate": "Share of confirmed merges later identified as incorrect (by review or ground truth).",
    "candidate_recall": "Share of true-match records whose correct entity appeared anywhere in the top-N candidates (needs ground truth).",
}

PERCENT_METRICS = ["match_rate", "hit_rate", "manual_review_rate", "precision", "recall", "f1_score",
                   "false_positive_rate", "false_negative_rate", "accuracy", "dispute_rate", "merge_error_rate",
                   "candidate_recall"]
HIGHER_IS_BETTER = {
    "match_rate": None, "hit_rate": True, "manual_review_rate": False, "precision": True, "recall": True,
    "f1_score": True, "false_positive_rate": False, "false_negative_rate": False, "accuracy": True,
    "dispute_rate": False, "merge_error_rate": False, "candidate_recall": True,
}


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


# ------------------------------------------------------------ label-free
def decision_counts(results: list[dict]) -> dict[str, int]:
    counts = {"MATCH": 0, "MANUAL_REVIEW": 0, "NO_MATCH": 0}
    for r in results:
        counts[r.get("decision", "NO_MATCH")] = counts.get(r.get("decision", "NO_MATCH"), 0) + 1
    return counts


def hit_rate(results: list[dict], acceptable_threshold: float) -> float | None:
    """HIT = best candidate score >= acceptable threshold (manual-review threshold)."""
    if not results:
        return None
    hits = sum(1 for r in results if r.get("overall_score") is not None and r["overall_score"] >= acceptable_threshold)
    return _pct(hits / len(results))


# ----------------------------------------------------------- with labels
def classify_record(result: dict, truth: dict | None) -> str | None:
    """Return TP / FP / FN / TN / REVIEW / UNLABELLED for one record."""
    if truth is None:
        return "UNLABELLED"
    decision = result.get("decision")
    if decision == "MANUAL_REVIEW":
        return "REVIEW"
    true_dec = (truth.get("true_decision") or "").upper()
    true_entity = truth.get("true_entity_id") or None
    if decision == "MATCH":
        return "TP" if (true_dec == "MATCH" and result.get("entity_id") == true_entity) else "FP"
    # NO_MATCH
    return "FN" if true_dec == "MATCH" else "TN"


def confusion_counts(results: list[dict], truth: dict[str, dict]) -> dict:
    """Count TP/FP/FN/TN (+ review/unlabelled) and keep per-record outcomes."""
    counts = {"TP": 0, "FP": 0, "FN": 0, "TN": 0, "REVIEW": 0, "UNLABELLED": 0}
    outcomes = {}
    review_true_match = 0
    for r in results:
        t = truth.get(r["incoming_id"])
        label = classify_record(r, t)
        counts[label] += 1
        outcomes[r["incoming_id"]] = label
        if label == "REVIEW" and t and (t.get("true_decision") or "").upper() == "MATCH":
            review_true_match += 1
    counts["review_true_match"] = review_true_match
    counts["labelled"] = len(results) - counts["UNLABELLED"]
    return {"counts": counts, "outcomes": outcomes}


def metrics_from_counts(tp: int, fp: int, fn: int, tn: int) -> dict[str, float | None]:
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall) if precision is not None and recall is not None else None
    return {
        "precision": _pct(precision),
        "recall": _pct(recall),
        "f1_score": _pct(f1),
        "false_positive_rate": _pct(safe_div(fp, fp + tn)),
        "false_negative_rate": _pct(safe_div(fn, fn + tp)),
        "accuracy": _pct(safe_div(tp + tn, tp + fp + fn + tn)),
    }


def candidate_recall(candidates_by_incoming: dict[str, list[str]], truth: dict[str, dict]) -> float | None:
    """Was the true entity anywhere in the top-N? (search quality with labels)."""
    relevant = [iid for iid, t in truth.items() if (t.get("true_decision") or "").upper() == "MATCH" and t.get("true_entity_id")]
    if not relevant:
        return None
    found = sum(1 for iid in relevant if truth[iid]["true_entity_id"] in candidates_by_incoming.get(iid, []))
    return _pct(found / len(relevant))


# ---------------------------------------------------------- human metrics
def dispute_rate(total_matches: int, disputes: int) -> float | None:
    if not total_matches:
        return None
    return _pct(disputes / total_matches)


def merge_error_rate(total_merges: int, incorrect: int) -> float | None:
    if not total_merges:
        return None
    return _pct(incorrect / total_merges)


# -------------------------------------------------------------- summary
def run_summary(results: list[dict], acceptable_threshold: float, truth: dict[str, dict] | None = None,
                candidates_by_incoming: dict[str, list[str]] | None = None, disputes: int = 0,
                total_merges: int = 0, incorrect_merges: int = 0) -> dict:
    """Compute every metric for one run. Results = list of result dicts."""
    n = len(results)
    counts = decision_counts(results)
    summary: dict = {
        "total_records": n,
        "total_matches": counts["MATCH"],
        "total_manual_reviews": counts["MANUAL_REVIEW"],
        "total_no_matches": counts["NO_MATCH"],
        "match_rate": _pct(safe_div(counts["MATCH"], n)),
        "hit_rate": hit_rate(results, acceptable_threshold),
        "manual_review_rate": _pct(safe_div(counts["MANUAL_REVIEW"], n)),
        "dispute_rate": dispute_rate(counts["MATCH"], disputes),
        "merge_error_rate": merge_error_rate(total_merges, incorrect_merges),
        "ground_truth_available": False,
        "precision": None, "recall": None, "f1_score": None, "accuracy": None,
        "false_positive_rate": None, "false_negative_rate": None, "candidate_recall": None,
        "tp": None, "fp": None, "fn": None, "tn": None, "review": None, "labelled": 0,
    }
    pools = [r.get("candidate_pool_size") for r in results if r.get("candidate_pool_size") is not None]
    masters = [r.get("master_size") for r in results if r.get("master_size")]
    summary["avg_candidates"] = round(sum(pools) / len(pools), 2) if pools else None
    summary["candidate_reduction_pct"] = (
        round((1 - (sum(pools) / len(pools)) / (sum(masters) / len(masters))) * 100, 2) if pools and masters else None
    )

    truth = {k: v for k, v in (truth or {}).items() if k in {r["incoming_id"] for r in results}}
    if truth:
        cm = confusion_counts(results, truth)
        c = cm["counts"]
        summary.update(metrics_from_counts(c["TP"], c["FP"], c["FN"], c["TN"]))
        summary.update({"tp": c["TP"], "fp": c["FP"], "fn": c["FN"], "tn": c["TN"], "review": c["REVIEW"],
                        "labelled": c["labelled"], "review_true_match": c["review_true_match"],
                        "ground_truth_available": True, "outcomes": cm["outcomes"]})
        if candidates_by_incoming is not None:
            summary["candidate_recall"] = candidate_recall(candidates_by_incoming, truth)
    return summary
