from matching.algorithm_config import DEFAULT_BLOCKING_PASSES
from matching.blocking import BlockingIndex, blocking_key, reduction_pct
from matching.preprocessing import normalize_record


def test_blocking_keys():
    n = normalize_record({"name": "Rahul Sharma", "phone": "+91 9876543210", "email": "A@B.com", "city": "Patna", "postal_code": "800001"})
    assert blocking_key("phone", n) == "9876543210"
    assert blocking_key("email", n) == "a@b.com"
    assert blocking_key("postal_surname", n) == "800001|sharma"
    assert blocking_key("city_surname", n) == "patna|sharma"
    assert blocking_key("phonetic_surname_city", n) == "patna|S650"
    assert blocking_key("first_token_city", n) == "patna|rahul"


def test_missing_values_produce_no_key():
    n = normalize_record({"name": "Rahul Sharma"})
    assert blocking_key("phone", n) is None
    assert blocking_key("city_surname", n) is None


def test_candidates_union_and_provenance(small_index):
    inc = normalize_record({"name": "RAHUL SHARMA", "phone": "+91 9876543210", "city": "Patna"})
    pool = small_index.candidates(inc, DEFAULT_BLOCKING_PASSES, full_scan_below=0)
    assert "C01023" in pool and "C00002" in pool          # both Rahul Sharmas in Patna
    assert "C00003" not in pool                             # Priya Singh in Lucknow is not a candidate
    assert "phone" in pool["C01023"] and "city_surname" in pool["C01023"]
    assert "phone" not in pool["C00002"]                    # the twin was only found via name-based passes
    # no duplicates: each candidate appears once with a list of passes
    assert all(len(set(p)) == len(p) for p in pool.values())


def test_phonetic_pass_catches_spelling_variation(small_index):
    inc = normalize_record({"name": "Rahul Sharmah", "city": "Patna"})
    pool = small_index.candidates(inc, ["phonetic_surname_city"], full_scan_below=0)
    assert "C01023" in pool


def test_full_scan_for_tiny_master(small_index):
    inc = normalize_record({"name": "Nobody Here"})
    pool = small_index.candidates(inc, DEFAULT_BLOCKING_PASSES, full_scan_below=100)
    assert len(pool) == small_index.size and all(p == ["full_scan"] for p in pool.values())


def test_reduction_metric(large_master):
    index = BlockingIndex(large_master)
    inc = normalize_record({"name": "Rahul Sharma", "phone": "9876543210", "city": "Patna", "postal_code": "800001"})
    pool = index.candidates(inc, DEFAULT_BLOCKING_PASSES, full_scan_below=0)
    assert 0 < len(pool) < index.size / 10
    assert reduction_pct(index.size, len(pool)) > 90
    assert reduction_pct(0, 0) is None


def test_value_frequencies(small_index):
    assert small_index.frequency("name", "rahul sharma") == 2
    assert small_index.frequency("phone", "9876543210") == 1
    assert small_index.frequency("phone", None) == 0
