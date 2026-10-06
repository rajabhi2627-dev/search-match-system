"""Decision engine and confidence score."""
from matching.algorithm_config import AlgorithmConfig
from matching.decision_engine import confidence_score, decide

CFG = AlgorithmConfig()   # 85 / 65 / 5


def test_match_rule():
    d = decide(94.2, 8.7, False, CFG)
    assert d.decision == "MATCH" and d.rule == "match"


def test_high_score_but_small_gap_is_review():
    d = decide(94.2, 1.4, False, CFG)
    assert d.decision == "MANUAL_REVIEW" and d.rule == "high_score_ambiguous"


def test_high_score_but_conflict_is_review():
    d = decide(91.0, 20.0, True, CFG, conflict_text="email differs")
    assert d.decision == "MANUAL_REVIEW" and d.rule == "high_score_conflict"
    assert "email differs" in d.reason


def test_mid_score_is_review():
    assert decide(70.0, 30.0, False, CFG).decision == "MANUAL_REVIEW"
    assert decide(84.9, 30.0, False, CFG).decision == "MANUAL_REVIEW"


def test_low_score_and_no_candidate():
    assert decide(42.3, 10.0, False, CFG).decision == "NO_MATCH"
    assert decide(None, None, False, CFG).rule == "no_candidate"


def test_thresholds_are_configurable():
    strict = AlgorithmConfig(match_threshold=95, manual_review_threshold=80, ambiguity_gap_threshold=10)
    assert decide(94.2, 8.7, False, strict).decision == "MANUAL_REVIEW"
    assert decide(96.0, 8.7, False, strict).decision == "MANUAL_REVIEW"     # gap 8.7 < 10
    assert decide(96.0, 12.0, False, strict).decision == "MATCH"
    assert decide(79.0, 12.0, False, strict).decision == "NO_MATCH"


def test_boundary_values_inclusive():
    assert decide(85.0, 5.0, False, CFG).decision == "MATCH"
    assert decide(65.0, 5.0, False, CFG).decision == "MANUAL_REVIEW"


def test_confidence_high_example():
    level, pts, factors = confidence_score(95, {"name": 96, "email": 100, "phone": 100, "address": 82, "dob": 100, "company": None}, 12, [])
    assert level == "HIGH" and pts >= 70
    assert {f["factor"] for f in factors} >= {"Overall similarity", "Strongly matching fields", "Score gap", "Conflicts"}


def test_confidence_drops_with_conflict_and_small_gap():
    conflicts = [{"severity": "CRITICAL", "message": "email differs"}]
    level, pts, _ = confidence_score(89, {"name": 96, "email": 20, "phone": 100, "address": 90, "dob": None, "company": None}, 2, conflicts)
    assert level in ("LOW", "MEDIUM") and pts < 70


def test_confidence_low_for_no_candidate():
    assert confidence_score(None, {}, None, [])[0] == "LOW"


def test_confidence_is_independent_of_score_alone():
    # same score, but one has only a single comparable field and zero gap → lower confidence
    rich, _, _ = confidence_score(100, {"name": 100, "email": 100, "phone": 100, "address": 100, "dob": 100, "company": 100}, 40, [])
    sparse, _, _ = confidence_score(100, {"name": 100, "email": None, "phone": None, "address": None, "dob": None, "company": None}, 0, [])
    assert rich == "HIGH" and sparse != "HIGH"
