"""Precision, recall, F1, FPR, FNR, HIT rate, dispute / merge-error rates, RAG thresholds and data generation."""
import pytest

from data.incoming_generator import SCENARIO_LABELS, generate_incoming
from data.master_generator import WORKED_EXAMPLE, find_twin_pairs, generate_master
from data.validators import data_quality_profile, validate_incoming_df
from performance.metrics import (
    candidate_recall, classify_record, confusion_counts, dispute_rate, hit_rate, merge_error_rate, metrics_from_counts, run_summary,
)
from performance.thresholds import rag_status
import pandas as pd


def test_metrics_from_counts():
    m = metrics_from_counts(tp=90, fp=10, fn=5, tn=95)
    assert m["precision"] == pytest.approx(90.0)
    assert m["recall"] == pytest.approx(94.74, abs=0.01)
    assert m["f1_score"] == pytest.approx(92.31, abs=0.01)
    assert m["false_positive_rate"] == pytest.approx(9.52, abs=0.01)
    assert m["false_negative_rate"] == pytest.approx(5.26, abs=0.01)
    assert m["accuracy"] == pytest.approx(92.5)


def test_metrics_undefined_when_no_denominator():
    m = metrics_from_counts(0, 0, 0, 0)
    assert all(v is None for v in m.values())


def test_classification_rules():
    truth_match = {"true_entity_id": "C1", "true_decision": "MATCH"}
    truth_none = {"true_entity_id": None, "true_decision": "NO_MATCH"}
    assert classify_record({"decision": "MATCH", "entity_id": "C1"}, truth_match) == "TP"
    assert classify_record({"decision": "MATCH", "entity_id": "C9"}, truth_match) == "FP"       # wrong entity
    assert classify_record({"decision": "MATCH", "entity_id": "C1"}, truth_none) == "FP"
    assert classify_record({"decision": "NO_MATCH", "entity_id": None}, truth_match) == "FN"
    assert classify_record({"decision": "NO_MATCH", "entity_id": None}, truth_none) == "TN"
    assert classify_record({"decision": "MANUAL_REVIEW", "entity_id": "C1"}, truth_match) == "REVIEW"
    assert classify_record({"decision": "MATCH", "entity_id": "C1"}, None) == "UNLABELLED"


def test_run_summary_without_ground_truth():
    results = [{"incoming_id": "a", "decision": "MATCH", "overall_score": 95, "entity_id": "C1"},
               {"incoming_id": "b", "decision": "MANUAL_REVIEW", "overall_score": 70, "entity_id": "C2"},
               {"incoming_id": "c", "decision": "NO_MATCH", "overall_score": 40, "entity_id": None},
               {"incoming_id": "d", "decision": "NO_MATCH", "overall_score": None, "entity_id": None}]
    s = run_summary(results, acceptable_threshold=65)
    assert s["match_rate"] == 25 and s["manual_review_rate"] == 25
    assert s["hit_rate"] == 50                       # two records with best score >= 65
    assert s["precision"] is None and s["recall"] is None and not s["ground_truth_available"]


def test_run_summary_with_ground_truth():
    results = [{"incoming_id": "a", "decision": "MATCH", "overall_score": 95, "entity_id": "C1"},
               {"incoming_id": "b", "decision": "MATCH", "overall_score": 90, "entity_id": "C2"},
               {"incoming_id": "c", "decision": "NO_MATCH", "overall_score": 40, "entity_id": None},
               {"incoming_id": "d", "decision": "NO_MATCH", "overall_score": 50, "entity_id": None},
               {"incoming_id": "e", "decision": "MANUAL_REVIEW", "overall_score": 75, "entity_id": "C5"}]
    truth = {"a": {"true_entity_id": "C1", "true_decision": "MATCH"}, "b": {"true_entity_id": "C9", "true_decision": "MATCH"},
             "c": {"true_entity_id": None, "true_decision": "NO_MATCH"}, "d": {"true_entity_id": "C4", "true_decision": "MATCH"},
             "e": {"true_entity_id": "C5", "true_decision": "MATCH"}}
    s = run_summary(results, 65, truth, candidates_by_incoming={"a": ["C1"], "b": ["C2", "C9"], "d": ["C8"], "e": ["C5"]})
    assert (s["tp"], s["fp"], s["fn"], s["tn"], s["review"]) == (1, 1, 1, 1, 1)
    assert s["precision"] == 50 and s["recall"] == 50 and s["false_positive_rate"] == 50 and s["false_negative_rate"] == 50
    assert s["candidate_recall"] == 75                # C1, C9, C5 found; C4 not
    assert s["ground_truth_available"]


def test_hit_dispute_merge_rates():
    assert hit_rate([], 65) is None
    assert dispute_rate(0, 0) is None
    assert dispute_rate(50, 2) == 4.0
    assert merge_error_rate(0, 0) is None
    assert merge_error_rate(20, 1) == 5.0


def test_rag_status_directions():
    assert rag_status(95, "higher_is_better", 90, 80) == "GREEN"
    assert rag_status(85, "higher_is_better", 90, 80) == "AMBER"
    assert rag_status(70, "higher_is_better", 90, 80) == "RED"
    assert rag_status(1, "lower_is_better", 2, 5) == "GREEN"
    assert rag_status(3, "lower_is_better", 2, 5) == "AMBER"
    assert rag_status(9, "lower_is_better", 2, 5) == "RED"
    assert rag_status(None, "lower_is_better", 2, 5) is None


# ----------------------------------------------------------- generators
def test_master_generation_is_deterministic_and_unique():
    a = generate_master(300, seed=1)
    b = generate_master(300, seed=1)
    assert a == b
    assert len(a) == 300
    assert len({r["entity_id"] for r in a}) == 300
    phones = [r["phone"] for r in a]
    assert len(set(phones)) == len(phones)
    assert any(r["email"] == WORKED_EXAMPLE["email"] for r in a)
    assert generate_master(1500, seed=1)[1022]["entity_id"] == "C01023"
    assert generate_master(1500, seed=1)[1022]["name"] == "Rahul Sharma"


def test_master_generation_contains_twins():
    recs = generate_master(1000, seed=3, twin_pct=3)
    assert len(find_twin_pairs(recs)) >= 10


def test_incoming_generation_scenarios_and_truth():
    masters = generate_master(500, seed=5)
    gen = generate_incoming(masters, 100, 70, 15, 5, 5, 5, seed=9)
    assert len(gen.records) == 100 and len(gen.ground_truth) == 100
    labels = {t["scenario"] for t in gen.ground_truth}
    assert labels == set(SCENARIO_LABELS.values())              # all 12 scenarios present
    assert sum(1 for t in gen.ground_truth if t["true_decision"] == "NO_MATCH") == 15
    assert sum(gen.scenario_counts.values()) == 100
    # deterministic
    again = generate_incoming(masters, 100, 70, 15, 5, 5, 5, seed=9)
    assert again.records == gen.records


def test_incoming_generation_rejects_bad_percentages():
    masters = generate_master(50, seed=5)
    with pytest.raises(ValueError):
        generate_incoming(masters, 10, 50, 10, 10, 10, 10)


def test_validation_and_quality():
    df = pd.DataFrame([{"name": "A", "email": "a@b.com", "phone": "9876543210"}, {"name": None, "email": "bad", "phone": "123"},
                       {"name": "A", "email": "a@b.com", "phone": "9876543210"}])
    report = validate_incoming_df(df)
    assert report.is_valid and report.duplicate_rows == 1
    q = data_quality_profile(df)
    assert q["missing_name_pct"] == pytest.approx(33.3, abs=0.1)
    assert q["invalid_email_pct"] == pytest.approx(33.3, abs=0.1)
    assert q["invalid_phone_pct"] == pytest.approx(33.3, abs=0.1)
    assert not validate_incoming_df(pd.DataFrame()).is_valid
    assert not validate_incoming_df(pd.DataFrame([{"city": "Patna"}])).is_valid
    assert not validate_incoming_df(None).is_valid
