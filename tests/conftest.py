"""Shared pytest fixtures."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.master_generator import WORKED_EXAMPLE, generate_master          # noqa: E402
from matching.algorithm_config import AlgorithmConfig                       # noqa: E402
from matching.blocking import BlockingIndex                                 # noqa: E402
from matching.pipeline import MatchEngine                                   # noqa: E402


@pytest.fixture(scope="session")
def small_master() -> list[dict]:
    """A hand-made master set containing the worked example and some look-alikes."""
    return [
        {"entity_id": "C01023", **WORKED_EXAMPLE},
        {"entity_id": "C00002", "name": "Rahul Sharma", "email": "rahul.s88@yahoo.com", "phone": "9123456789",
         "address": "45 Boring Road, Patna", "date_of_birth": "1990-02-02", "company": "Infosys Ltd", "city": "Patna",
         "state": "Bihar", "postal_code": "800013"},
        {"entity_id": "C00003", "name": "Priya Singh", "email": "priya.singh@gmail.com", "phone": "9000000001",
         "address": "7 Station Road, Lucknow", "date_of_birth": "1992-07-19", "company": "HDFC Bank", "city": "Lucknow",
         "state": "Uttar Pradesh", "postal_code": "226001"},
        {"entity_id": "C00004", "name": "Amit Verma", "email": "amit.verma@outlook.com", "phone": "9000000002",
         "address": "90 Civil Lines, Kanpur", "date_of_birth": "1985-11-30", "company": "Wipro Limited", "city": "Kanpur",
         "state": "Uttar Pradesh", "postal_code": "208001"},
        {"entity_id": "C00005", "name": "Sneha Patel", "email": "sneha.patel@gmail.com", "phone": "9000000003",
         "address": "3 CG Road, Ahmedabad", "date_of_birth": "1995-01-05", "company": "Zomato", "city": "Ahmedabad",
         "state": "Gujarat", "postal_code": "380009"},
    ]


@pytest.fixture(scope="session")
def large_master() -> list[dict]:
    return generate_master(2000, seed=42, twin_pct=2.0)


@pytest.fixture(scope="session")
def config() -> AlgorithmConfig:
    cfg = AlgorithmConfig()
    cfg.full_scan_if_master_below = 0      # always use blocking in tests
    return cfg


@pytest.fixture(scope="session")
def small_index(small_master) -> BlockingIndex:
    return BlockingIndex(small_master)


@pytest.fixture(scope="session")
def engine(config, small_index) -> MatchEngine:
    return MatchEngine(config, small_index)


@pytest.fixture(scope="session")
def large_engine(config, large_master) -> MatchEngine:
    return MatchEngine(config, BlockingIndex(large_master))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the database layer at a temporary SQLite file."""
    from database import database as dbmod

    path = tmp_path / "test.db"
    monkeypatch.setenv("SMM_DB_PATH", str(path))
    dbmod.reset_engine()
    dbmod.init_db(str(path))
    yield str(path)
    dbmod.reset_engine()
