"""Rule-based regression testing and stability testing.

REGRESSION TEST
    Run the same golden dataset (records with ground-truth labels) through two
    algorithm versions and compare the metrics.  If a "higher is better"
    metric drops by more than `material_pp` percentage points (or a "lower is
    better" metric rises by more), the test reports
    "Potential regression detected".

STABILITY TEST
    Run identical input N times through the same engine and check that the
    best candidate, score and decision are identical every time.  Because the
    algorithm is deterministic the expected result is STABLE.

Both tests are purely deterministic rules – no AI is involved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BlockingIndex
from matching.pipeline import MatchEngine
from performance.metrics import HIGHER_IS_BETTER, run_summary
from performance.version_comparison import compare_versions

REGRESSION_METRICS = ["precision", "recall", "f1_score", "false_positive_rate", "false_negative_rate",
                      "hit_rate", "manual_review_rate"]


def outcomes_to_results(outcomes, incoming_ids: list[str]) -> list[dict]:
    """MatchOutcome list → plain result dicts understood by metrics.run_summary."""
    rows = []
    for iid, o in zip(incoming_ids, outcomes):
        rows.append({
            "incoming_id": iid,
            "entity_id": o.best_entity_id,
            "overall_score": o.best_score,
            "decision": o.decision,
            "candidate_pool_size": o.pool_size,
            "master_size": o.master_size,
        })
    return rows


def evaluate_config(config: AlgorithmConfig, index: BlockingIndex, records: list[dict],
                    truth: dict[str, dict] | None) -> tuple[dict, list]:
    """Run a config on records and return (metrics summary, outcomes)."""
    engine = MatchEngine(config, index)
    outcomes = engine.match_many(records)
    ids = [r.get("incoming_id") or f"row-{i}" for i, r in enumerate(records)]
    results = outcomes_to_results(outcomes, ids)
    cands = {iid: [c.entity_id for c in o.candidates] for iid, o in zip(ids, outcomes)}
    summary = run_summary(results, config.manual_review_threshold, truth, cands)
    return summary, outcomes


@dataclass
class RegressionReport:
    baseline: str
    candidate: str
    table: pd.DataFrame
    degraded: list[str] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)
    regression_detected: bool = False
    ground_truth_available: bool = False
    records_tested: int = 0
    changed_decisions: int = 0
    changed_rows: pd.DataFrame | None = None

    @property
    def verdict(self) -> str:
        if self.regression_detected:
            return "Potential regression detected."
        return "No material regression detected."


def run_regression(baseline: AlgorithmConfig, candidate: AlgorithmConfig, index: BlockingIndex,
                   records: list[dict], truth: dict[str, dict] | None, material_pp: float = 2.0) -> RegressionReport:
    m_a, out_a = evaluate_config(baseline, index, records, truth)
    m_b, out_b = evaluate_config(candidate, index, records, truth)
    table = compare_versions(m_a, m_b, f"v{baseline.version_name}", f"v{candidate.version_name}", material_pp)

    degraded, improved = [], []
    for _, row in table.iterrows():
        key = row["_key"]
        if key not in REGRESSION_METRICS or row["Change (pp)"] is None:
            continue
        direction = HIGHER_IS_BETTER.get(key)
        delta = row["Change (pp)"]
        if direction is None or abs(delta) <= material_pp:
            continue
        worse = delta < 0 if direction else delta > 0
        (degraded if worse else improved).append(row["Metric"])

    changed = []
    for i, (a, b) in enumerate(zip(out_a, out_b)):
        if a.decision != b.decision or a.best_entity_id != b.best_entity_id:
            changed.append({
                "Row": i + 1,
                "Incoming": records[i].get("name"),
                f"v{baseline.version_name} decision": a.decision,
                f"v{candidate.version_name} decision": b.decision,
                f"v{baseline.version_name} entity": a.best_entity_id or "-",
                f"v{candidate.version_name} entity": b.best_entity_id or "-",
                f"v{baseline.version_name} score": a.best_score,
                f"v{candidate.version_name} score": b.best_score,
            })

    return RegressionReport(
        baseline=baseline.version_name, candidate=candidate.version_name, table=table,
        degraded=degraded, improved=improved, regression_detected=bool(degraded),
        ground_truth_available=bool(m_a.get("ground_truth_available")), records_tested=len(records),
        changed_decisions=len(changed), changed_rows=pd.DataFrame(changed) if changed else None,
    )


# ------------------------------------------------------------- stability
@dataclass
class StabilityReport:
    runs: int
    records: int
    stable: bool
    differences: list[dict] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "STABLE" if self.stable else "UNSTABLE"


def stability_test(engine: MatchEngine, records: list[dict], runs: int = 5) -> StabilityReport:
    """Run the same records `runs` times and compare (entity, score, decision)."""
    snapshots = []
    for _ in range(runs):
        outs = engine.match_many(records)
        snapshots.append([(o.best_entity_id, o.best_score, o.decision) for o in outs])
    differences = []
    base = snapshots[0]
    for run_no, snap in enumerate(snapshots[1:], start=2):
        for i, (a, b) in enumerate(zip(base, snap)):
            if a != b:
                differences.append({"run": run_no, "row": i + 1, "first_run": a, "this_run": b})
    return StabilityReport(runs=runs, records=len(records), stable=not differences, differences=differences)
