"""Exact matching, fuzzy matching, the worked example and the end-to-end pipeline."""
from data.incoming_generator import worked_example_incoming
from matching.exact_match import exact_matches, has_strong_exact
from matching.fuzzy_match import (
    address_similarity, company_similarity, dob_similarity, email_similarity, name_similarity, phone_similarity,
)
from matching.preprocessing import normalize_record


# ------------------------------------------------------------ exact rules
def test_exact_rules_single_vs_combination():
    inc = normalize_record({"name": "Rahul Sharma", "email": "rahul.sharma@gmail.com", "date_of_birth": "1988-05-14"})
    cand = normalize_record({"name": "RAHUL SHARMA", "email": "Rahul.Sharma@GMAIL.com", "date_of_birth": "14/05/1988", "phone": "9876543210"})
    fired = {r["rule_id"] for r in exact_matches(inc, cand)}
    assert "exact_email" in fired and "exact_name_dob" in fired and "exact_email_name" in fired
    assert "exact_phone" not in fired              # incoming has no phone
    assert has_strong_exact(exact_matches(inc, cand))


def test_single_field_exact_is_not_strong():
    inc = normalize_record({"email": "x@y.com", "name": "A B"})
    cand = normalize_record({"email": "x@y.com", "name": "C D"})
    fired = exact_matches(inc, cand)
    assert [r["rule_id"] for r in fired] == ["exact_email"]
    assert not has_strong_exact(fired)


# ------------------------------------------------------------ fuzzy fields
def test_name_similarity_variants():
    assert name_similarity("rahul sharma", "rahul sharma")["score"] == 100
    assert name_similarity("rahul sharma", "sharma rahul")["score"] >= 85          # word order
    assert name_similarity("rahul sharma", "rahul sharme")["score"] >= 85          # typo
    assert name_similarity("rahul sharma", "priya singh")["score"] < 50
    assert name_similarity("rahul sharma", None)["score"] is None
    details = name_similarity("rahul sharma", "rahul s")
    assert {"wratio", "ratio", "token_sort_ratio", "token_set_ratio", "jaro_winkler"} <= set(details)


def test_address_similarity_after_normalization():
    a = normalize_record({"address": "12 MG Road, Patna"})["norm"]["address"]
    b = normalize_record({"address": "12 Mahatma Gandhi Rd Patna"})["norm"]["address"]
    assert address_similarity(a, b)["score"] == 100
    assert address_similarity("12 mg rd patna", "90 civil lines kanpur")["score"] < 50


def test_email_similarity_rules():
    assert email_similarity("a@b.com", "a@b.com")["score"] == 100
    typo = email_similarity("rahul.sharma@gmail.com", "rahul.sharme@gmail.com")
    assert typo["score"] > 85 and typo["username"] > 85 and typo["domain"] == 100
    different = email_similarity("rahul.sharma@gmail.com", "contact.rahul123@zoho.in")
    assert different["score"] < 30


def test_phone_similarity_is_digit_based():
    assert phone_similarity("9876543210", "9876543210")["score"] == 100
    assert phone_similarity("8876543210", "9876543210")["score"] == 70      # last 8 equal
    assert phone_similarity("9999543210", "9876543210")["score"] == 40      # last 6 equal
    assert phone_similarity("1111111111", "9876543210")["score"] == 0
    assert phone_similarity(None, "9876543210")["score"] is None


def test_dob_and_company():
    assert dob_similarity("1988-05-14", "1988-05-14")["score"] == 100
    assert dob_similarity("1988-05-14", "1988-05-15")["score"] == 0
    assert dob_similarity(None, "1988-05-14")["score"] is None
    assert company_similarity("tata consultancy services", "tata consultancy services")["score"] == 100


# ---------------------------------------------------------- worked example
def test_worked_example_matches_c01023(engine):
    outcome = engine.match_record(worked_example_incoming())
    assert outcome.decision == "MATCH"
    assert outcome.best_entity_id == "C01023"
    assert outcome.best.field_scores["phone"] == 100
    assert outcome.best.field_scores["email"] == 100
    assert outcome.best.field_scores["name"] == 100
    assert outcome.best.field_scores["address"] >= 90
    assert outcome.best_score >= 90
    assert "phone" in outcome.best.blocking_methods and "email" in outcome.best.blocking_methods
    assert outcome.score_gap >= 5
    assert outcome.confidence == "HIGH"
    assert len(outcome.candidates) >= 2                  # the twin Rahul Sharma is also a candidate
    assert outcome.candidates[0].rank == 1


def test_no_candidate_gives_no_match(engine):
    outcome = engine.match_record({"name": "Zara Unknown", "city": "Kochi", "phone": "7000000000"})
    assert outcome.decision == "NO_MATCH"
    assert outcome.best is None and outcome.pool_size == 0


def test_sparse_record_with_twins_is_ambiguous(engine):
    outcome = engine.match_record({"name": "Rahul Sharma", "city": "Patna"})
    assert outcome.decision == "MANUAL_REVIEW"
    assert outcome.decision_rule == "high_score_ambiguous"
    assert outcome.score_gap == 0


def test_conflicting_email_goes_to_review(engine):
    rec = worked_example_incoming() | {"email": "office.rahul77@protonmail.com"}
    outcome = engine.match_record(rec)
    assert outcome.decision == "MANUAL_REVIEW"
    assert outcome.critical_conflict
    assert any(c["rule_id"] == "phone_vs_email" for c in outcome.best.conflicts)


def test_missing_fields_are_renormalized_not_zero(engine):
    rec = worked_example_incoming() | {"email": None, "date_of_birth": None, "company": None}
    outcome = engine.match_record(rec)
    bd = outcome.best.breakdown
    assert set(bd["missing_fields"]) == {"email", "dob", "company"}
    assert abs(sum(bd["effective_weights"].values()) - 100) < 0.01
    assert outcome.decision == "MATCH"


def test_pipeline_is_deterministic(engine):
    rec = worked_example_incoming()
    a, b = engine.match_record(rec), engine.match_record(rec)
    assert (a.best_entity_id, a.best_score, a.decision, a.confidence) == (b.best_entity_id, b.best_score, b.decision, b.confidence)
    assert [c.entity_id for c in a.candidates] == [c.entity_id for c in b.candidates]


def test_large_master_reduction(large_engine):
    outcome = large_engine.match_record(worked_example_incoming())
    assert outcome.master_size == 2000
    assert outcome.pool_size < 100
    assert outcome.reduction_pct > 95
    assert outcome.best_entity_id == "C01023"
