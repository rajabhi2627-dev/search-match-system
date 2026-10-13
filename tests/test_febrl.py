"""FEBRL benchmark loader: parsing, column mapping, master/incoming split and ground truth."""
import io

import pandas as pd
import pytest

from data.febrl_loader import (
    FEBRL_DATASETS, SCENARIO_DUP, SCENARIO_HOLDOUT, bundled_available, entity_id_for, load_bundled,
    parse_rec_id, preview_frame, read_febrl, split_febrl, to_record,
)
from matching.blocking import BlockingIndex
from matching.pipeline import MatchEngine

SAMPLE = """rec_id, given_name, surname, street_number, address_1, address_2, suburb, postcode, state, date_of_birth, soc_sec_id
rec-1-org, michaela, neumann, 8, stanley street, miami, winston hills, 4223, nsw, 19151111, 5304218
rec-1-dup-0, michaela, neumman, 8, stanley street, miami, winston hills, 4223, nsw, 19151111, 5304218
rec-2-org, courtney, painter, 12, pinkerton circuit, bega flats, richlands, 4560, vic, 19161214, 4066625
rec-2-dup-0, courtney, painter, 12, pinkerton circuit, bega flats, richlands, 4560, vic, 19161214, 4066625
rec-3-org, lachlan, berry, 69, giblin street, killarney, bittern, 4814, qld, 19990219, 7364009
rec-3-dup-0, lachlan, berry, 69, giblin street, killarney, bittern, 4814, qld, 19990219, 7364009
rec-3-dup-1, lachlna, berry, 69, giblin st, killarney, bittern, 4814, qld, 19990291, 7364009
rec-4-org, , waller, 6, tullaroop street, willaroo, st james, 4011, wa, 19081209, 6988048
rec-4-dup-0, , waller, 6, tullaroop street, willaroo, st james, 4011, wa, 19081209, 6988048
rec-5-org, deakin, sondergeld, 48, goldfinch circuit, kooltuo, canterbury, 2776, vic, 19600210, 2635962
rec-5-dup-0, deakin, sondergeld, 48, goldfinch circuit, kooltuo, canterbury, 2776, vic, 19600210, 2635962
"""


@pytest.fixture
def sample_df():
    return read_febrl(io.BytesIO(SAMPLE.encode()))


def test_parse_rec_id():
    assert parse_rec_id("rec-1070-org") == (1070, "org", None)
    assert parse_rec_id("rec-1070-dup-2") == (1070, "dup", 2)
    with pytest.raises(ValueError):
        parse_rec_id("customer-17")


def test_read_strips_whitespace_and_validates_columns(sample_df):
    assert list(sample_df.columns)[:3] == ["rec_id", "given_name", "surname"]
    assert sample_df.iloc[0]["given_name"] == "michaela"          # leading space removed
    with pytest.raises(ValueError):
        read_febrl(io.BytesIO(b"name,email\nx,y\n"))


def test_column_mapping(sample_df):
    rec = to_record(sample_df.iloc[0])
    assert rec["name"] == "michaela neumann"
    assert rec["address"] == "8 stanley street miami"
    assert rec["city"] == "winston hills" and rec["state"] == "NSW" and rec["postal_code"] == "4223"
    assert rec["date_of_birth"] == "1915-11-11"                   # YYYYMMDD → ISO
    assert rec["phone"] == "5304218"                               # soc_sec_id in the identifier slot
    assert rec["email"] is None and rec["company"] is None
    assert to_record(sample_df.iloc[0], id_as_phone=False)["phone"] is None
    assert to_record(sample_df.iloc[7])["name"] == "waller"       # missing given name handled


def test_split_without_holdout(sample_df):
    s = split_febrl(sample_df, dataset="sample", holdout_pct=0)
    assert len(s.master_records) == 5 and len(s.incoming_records) == 6
    assert {m["entity_id"] for m in s.master_records} == {entity_id_for(i) for i in range(1, 6)}
    assert all(t["true_decision"] == "MATCH" for t in s.ground_truth)
    assert all(r["scenario"] == SCENARIO_DUP for r in s.incoming_records)
    # duplicates of rec-3 both point at F00003
    rows = [t for t in s.ground_truth if t["true_entity_id"] == "F00003"]
    assert len(rows) == 2


def test_split_with_holdout_creates_true_no_match(sample_df):
    s = split_febrl(sample_df, dataset="sample", holdout_pct=40, seed=1)   # 40% of 5 → 2 held out
    assert s.stats["held_out_originals"] == 2 and len(s.master_records) == 3
    held = [t for t in s.ground_truth if t["true_decision"] == "NO_MATCH"]
    assert held and all(t["true_entity_id"] is None for t in held)
    assert sum(1 for r in s.incoming_records if r["scenario"] == SCENARIO_HOLDOUT) == len(held)
    # deterministic
    s2 = split_febrl(sample_df, dataset="sample", holdout_pct=40, seed=1)
    assert [m["entity_id"] for m in s2.master_records] == [m["entity_id"] for m in s.master_records]


def test_engine_matches_febrl_duplicates(sample_df, config):
    s = split_febrl(sample_df, dataset="sample", holdout_pct=0)
    engine = MatchEngine(config, BlockingIndex(s.master_records))
    outcomes = engine.match_many(s.incoming_records)
    truth = {t["row"]: t["true_entity_id"] for t in s.ground_truth}
    for i, o in enumerate(outcomes):
        assert o.best_entity_id == truth[i]                        # right candidate ranked first
    assert outcomes[0].decision == "MATCH"                         # one-letter surname typo
    assert outcomes[1].decision == "MATCH"                         # exact copy, score 100
    assert outcomes[0].best_score < outcomes[1].best_score


def test_preview_frame_pairs(sample_df):
    p = preview_frame(sample_df, n=3)
    assert len(p) == 3 and list(p["Entity"]) == ["F00001", "F00002", "F00003"]
    assert p.iloc[0]["Duplicate name"] == "michaela neumman"


@pytest.mark.skipif(not bundled_available("dataset1"), reason="bundled FEBRL files not present")
def test_bundled_dataset1_structure():
    df = load_bundled("dataset1")
    s = split_febrl(df, dataset="dataset1", holdout_pct=10)
    assert s.stats["originals"] == 500 and s.stats["duplicates"] == 500
    assert s.stats["held_out_originals"] == 50 and s.stats["master"] == 450
    assert s.stats["true_match"] == 450 and s.stats["true_no_match"] == 50
    assert all(k in FEBRL_DATASETS for k in ("dataset1", "dataset2", "dataset3", "dataset4"))
