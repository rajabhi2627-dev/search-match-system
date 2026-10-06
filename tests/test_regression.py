"""Regression testing, stability testing, version comparison and the database workflow."""
import pandas as pd

from data.incoming_generator import generate_incoming
from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BlockingIndex
from matching.pipeline import MatchEngine
from performance.regression import run_regression, stability_test
from performance.version_comparison import aggregate_runs, compare_versions, verdict


def _dataset(master):
    gen = generate_incoming(master, 60, 70, 15, 5, 5, 5, seed=11)
    records = [{"incoming_id": f"I{i:04d}", **{k: v for k, v in r.items() if k != "scenario"}} for i, r in enumerate(gen.records)]
    truth = {f"I{t['row']:04d}": {"true_entity_id": t["true_entity_id"], "true_decision": t["true_decision"]} for t in gen.ground_truth}
    return records, truth


def test_stability_test_is_stable(large_engine, large_master):
    records, _ = _dataset(large_master)
    report = stability_test(large_engine, records, runs=5)
    assert report.stable and report.verdict == "STABLE" and report.runs == 5


def test_stability_detects_differences(large_master):
    """A deliberately non-deterministic engine must be reported UNSTABLE."""
    records, _ = _dataset(large_master)
    cfg = AlgorithmConfig()
    engine = MatchEngine(cfg, BlockingIndex(large_master))
    calls = {"n": 0}
    original = engine.match_record

    def flaky(record):
        out = original(record)
        calls["n"] += 1
        if calls["n"] > len(records):          # from the second run on, flip decisions
            out.decision = "NO_MATCH" if out.decision == "MATCH" else out.decision
        return out

    engine.match_record = flaky
    report = stability_test(engine, records, runs=2)
    assert not report.stable and report.differences


def test_regression_no_change_for_identical_configs(large_master):
    records, truth = _dataset(large_master)
    index = BlockingIndex(large_master)
    a = AlgorithmConfig(version_name="1.0")
    b = AlgorithmConfig(version_name="1.1")
    report = run_regression(a, b, index, records, truth, material_pp=2.0)
    assert not report.regression_detected
    assert report.changed_decisions == 0
    assert report.ground_truth_available


def test_regression_detects_degradation(large_master):
    records, truth = _dataset(large_master)
    index = BlockingIndex(large_master)
    baseline = AlgorithmConfig(version_name="1.0")
    # a deliberately bad version: phone-only blocking and very loose thresholds → recall / FPR suffer
    bad = AlgorithmConfig(version_name="1.1", blocking_passes=["phone"], match_threshold=40, manual_review_threshold=30, ambiguity_gap_threshold=0)
    report = run_regression(baseline, bad, index, records, truth, material_pp=2.0)
    assert report.regression_detected
    assert report.verdict == "Potential regression detected."
    assert report.degraded
    assert isinstance(report.table, pd.DataFrame)


def test_version_comparison_verdicts():
    assert verdict("precision", 4.0) == "Improvement"
    assert verdict("precision", -4.0) == "Degradation"
    assert verdict("manual_review_rate", -3.0) == "Improvement"
    assert verdict("false_positive_rate", 1.0) == "Degradation"
    assert verdict("precision", None) == "Not available"
    assert verdict("precision", 0.5, material_pp=2.0) == "No material change"
    table = compare_versions({"precision": 91, "recall": None}, {"precision": 95, "recall": 80}, "v1.0", "v1.1")
    row = table.set_index("Metric").loc["Precision"]
    assert row["Change (pp)"] == 4 and row["Verdict"] == "Improvement"
    assert table.set_index("Metric").loc["Recall"]["Verdict"] == "Not available"


def test_aggregate_runs_averages_ignoring_none():
    agg = aggregate_runs([{"hit_rate": 80, "precision": None}, {"hit_rate": 90, "precision": 95}])
    assert agg["hit_rate"] == 85 and agg["precision"] == 95 and agg["runs"] == 2


# ------------------------------------------------------- database workflow
def test_end_to_end_workflow_with_database(tmp_db):
    from database import repository as repo
    from database.database import get_session
    from workflows.runner import generate_incoming_data, generate_master_data, run_batch

    m = generate_master_data(300, seed=2, mode="replace", actor="test")
    assert m.inserted == 300
    inc = generate_incoming_data(40, 70, 15, 5, 5, 5, seed=3, store_ground_truth=True, run_now=True, actor="test")
    assert inc.run_id is not None and inc.ground_truth_labels == 40

    with get_session() as session:
        run = repo.get_run(session, inc.run_id)
        assert run.total_records == 40
        assert run.total_matches + run.total_manual_reviews + run.total_no_matches == 40
        assert run.ground_truth_available and run.precision is not None
        results = repo.get_results(session, inc.run_id)
        assert len(results) == 40
        cands = repo.get_candidates(session, inc.run_id, results[0]["incoming_id"])
        assert cands == [] or cands[0]["rank"] == 1

        # create v1.1 and re-run → a second run with a different version, history preserved
        cfg = repo.get_active_config(session)
        cfg.version_name = "1.1"
        cfg.weights = {"name": 20, "email": 25, "phone": 30, "address": 15, "dob": 5, "company": 5}
        repo.create_version(session, cfg, "phone weight up", activate=True)
    second = run_batch(inc.batch_id, actor="test")
    with get_session() as session:
        runs = repo.list_runs(session)
        assert [r.algorithm_version for r in runs] == ["1.0", "1.1"]
        assert len(repo.get_results(session, runs[0].run_id)) == 40          # first run untouched

        # a human review that disputes a MATCH increases the dispute rate
        match_result = next(r for r in repo.get_results(session, second.run_id) if r["decision"] == "MATCH")
        repo.add_review(session, match_result, "REJECT_MATCH", "tester", "looks wrong")
        run2 = repo.get_run(session, second.run_id)
        assert run2.dispute_rate is not None and run2.dispute_rate > 0

        # merge + reverse → merge error rate
        other = next(r for r in repo.get_results(session, second.run_id) if r["decision"] == "MATCH" and r["match_id"] != match_result["match_id"])
        merge = repo.confirm_merge(session, other, {}, "ok", "tester")
        repo.reverse_merge(session, merge.merge_id, "wrong person", "tester")
        run2 = repo.get_run(session, second.run_id)
        assert run2.merge_error_rate == 100.0

        log = repo.audit_logs(session)
        assert {"DATA_GENERATED", "MATCH_RUN", "ALGORITHM_CREATED", "MANUAL_REVIEW", "MERGE_CONFIRMED", "MERGE_REVERSED"} <= set(log["Action Type"])
