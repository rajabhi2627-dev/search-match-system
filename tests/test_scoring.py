"""Weighted scoring, missing values, rare-value weighting, conflicts, ranking and score gap."""
import pytest

from matching.conflict_detection import detect_conflicts, detect_set_conflicts, has_critical
from matching.ranking import rank_candidates, score_gap
from matching.scoring import effective_weights, information_factor, overall_score
from matching.types import CandidateScore

WEIGHTS = {"name": 25, "email": 25, "phone": 25, "address": 15, "dob": 5, "company": 5}


def test_weighted_average_matches_brief_example():
    scores = {"name": 92, "email": 100, "phone": 100, "address": 82, "dob": 100, "company": None}
    result = overall_score(scores, WEIGHTS)
    # company missing → weights re-normalized over 95 → (92·25 + 100·25 + 100·25 + 82·15 + 100·5) / 95 = 95.05
    assert result["overall"] == pytest.approx(95.1, abs=0.05)
    assert result["missing_fields"] == ["company"]
    assert abs(sum(result["effective_weights"].values()) - 100) < 0.01


def test_all_fields_present():
    scores = {"name": 100, "email": 100, "phone": 100, "address": 100, "dob": 100, "company": 100}
    assert overall_score(scores, WEIGHTS)["overall"] == 100


def test_missing_field_is_not_zero():
    with_dob = overall_score({"name": 90, "email": 90, "phone": 90, "address": 90, "dob": 0, "company": 90}, WEIGHTS)["overall"]
    without_dob = overall_score({"name": 90, "email": 90, "phone": 90, "address": 90, "dob": None, "company": 90}, WEIGHTS)["overall"]
    assert without_dob == 90 and with_dob < 90


def test_effective_weights_renormalize():
    eff = effective_weights(WEIGHTS, ["name", "phone"])
    assert eff == {"name": 50.0, "phone": 50.0}
    assert effective_weights(WEIGHTS, []) == {}


def test_information_factor_is_capped_and_monotonic():
    unique = information_factor(1, 5000)
    common = information_factor(2500, 5000)
    assert 0.7 <= common < unique <= 1.5
    assert information_factor(0, 5000) == 1.0


def test_rare_value_weighting_cannot_override_weights():
    scores = {"name": 100, "email": 50, "phone": 100, "address": 50, "dob": None, "company": None}
    base = overall_score(scores, WEIGHTS)["overall"]
    boosted = overall_score(scores, WEIGHTS, factors={"phone": 1.5, "name": 1.5, "email": 0.7, "address": 0.7})["overall"]
    assert boosted > base
    assert boosted - base < 15                      # effect is bounded


# ------------------------------------------------------------- conflicts
def test_conflict_strong_phone_different_email_is_critical():
    conflicts = detect_conflicts({"name": 96, "phone": 100, "address": 90, "email": 20, "dob": None, "company": None})
    assert has_critical(conflicts)
    assert any(c.rule_id == "phone_vs_email" for c in conflicts)


def test_conflict_strong_name_different_phone():
    conflicts = detect_conflicts({"name": 95, "phone": 0, "email": None, "address": 80, "dob": None, "company": None})
    assert any(c.rule_id == "name_vs_phone" and c.severity == "CRITICAL" for c in conflicts)


def test_warning_conflicts_do_not_block():
    conflicts = detect_conflicts({"name": 95, "phone": 100, "email": 100, "address": 90, "dob": 0, "company": None})
    assert conflicts and not has_critical(conflicts)


def test_no_conflict_on_clean_match():
    assert detect_conflicts({"name": 100, "phone": 100, "email": 100, "address": 95, "dob": 100, "company": 90}) == []


def _cand(eid, overall, phone=None, email=None):
    return CandidateScore(entity_id=eid, master={}, field_scores={"phone": phone, "email": email}, field_details={}, breakdown={},
                          overall=overall, blocking_methods=[], exact_rules=[])


def test_set_conflict_split_identifiers():
    ranked = [_cand("A", 90, phone=100, email=20), _cand("B", 88, phone=0, email=100)]
    conflicts = detect_set_conflicts(ranked)
    assert conflicts and conflicts[0].rule_id == "split_identifiers"
    assert detect_set_conflicts([_cand("A", 90, phone=100, email=100)]) == []


# --------------------------------------------------------------- ranking
def test_ranking_order_and_gap():
    cands = [_cand("C3", 74.5), _cand("C1", 94.2), _cand("C2", 88.7), _cand("C4", 65.4), _cand("C5", 61.2), _cand("C6", 10)]
    top = rank_candidates(cands, top_n=5)
    assert [c.entity_id for c in top] == ["C1", "C2", "C3", "C4", "C5"]
    assert [c.rank for c in top] == [1, 2, 3, 4, 5]
    assert score_gap(top) == pytest.approx(5.5)
    assert top[0].gap_to_next == pytest.approx(5.5)


def test_ranking_tie_break_is_deterministic():
    top = rank_candidates([_cand("Z", 90), _cand("A", 90)], top_n=5)
    assert [c.entity_id for c in top] == ["A", "Z"]
    assert score_gap(top) == 0


def test_single_candidate_gap_equals_score():
    top = rank_candidates([_cand("A", 87.3)], top_n=5)
    assert score_gap(top) == pytest.approx(87.3)
    assert score_gap([]) is None
