"""High-level workflows used by BOTH the Streamlit pages and the seed script.

    generate_master_data()   – synthetic master records → database
    generate_incoming_data() – synthetic incoming batch (+ ground truth) → database
    run_batch()              – match a stored batch with an algorithm version → results + run
    match_records()          – in-memory matching (Search page, uploads before saving)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd

from data.incoming_generator import GenerationResult, generate_incoming
from data.master_generator import generate_master
from data.validators import data_quality_profile
from database import repository as repo
from database.database import get_session, init_db
from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BlockingIndex
from matching.pipeline import MatchEngine
from matching.types import MatchOutcome
from utils.helpers import RECORD_FIELDS, load_config
from utils.logger import get_logger

log = get_logger("workflows")


# ---------------------------------------------------------------- engine
def build_index() -> BlockingIndex:
    with get_session() as session:
        records = repo.load_master_records(session)
    return BlockingIndex(records)


def active_config() -> AlgorithmConfig:
    with get_session() as session:
        return repo.get_active_config(session)


def match_records(records: list[dict], cfg: AlgorithmConfig | None = None, index: BlockingIndex | None = None) -> list[MatchOutcome]:
    """Match records in memory without persisting anything."""
    cfg = cfg or active_config()
    index = index or build_index()
    return MatchEngine(cfg, index).match_many(records)


# ------------------------------------------------------------ master data
@dataclass
class MasterGenerationSummary:
    inserted: int
    total: int
    mode: str
    example_entity_id: str | None


def generate_master_data(n: int, seed: int | None = None, mode: str = "replace", twin_pct: float | None = None,
                         actor: str = "user") -> MasterGenerationSummary:
    cfg = load_config().get("generator", {})
    seed = cfg.get("seed", 42) if seed is None else seed
    twin_pct = cfg.get("twin_pct", 2) if twin_pct is None else twin_pct
    init_db()
    with get_session() as session:
        repo.ensure_defaults(session)
        if mode == "replace":
            repo.clear_master_and_dependents(session, actor)
            start = 1
        else:
            start = repo.next_entity_index(session)
        records = generate_master(n, seed=seed, twin_pct=twin_pct, start_index=start, include_example=(mode == "replace"))
        repo.insert_master_records(session, records, actor, action="DATA_GENERATED")
        total = repo.master_count(session)
    example = next((r["entity_id"] for r in records if r["email"] == "rahul.sharma@gmail.com"), None)
    log.info("Generated %s master records (mode=%s)", len(records), mode)
    return MasterGenerationSummary(inserted=len(records), total=total, mode=mode, example_entity_id=example)


# ---------------------------------------------------------- incoming data
@dataclass
class IncomingGenerationSummary:
    batch_id: str
    records: int
    scenario_counts: dict
    twins_added: int
    ground_truth_labels: int
    run_id: str | None = None


def generate_incoming_data(n: int, match_pct: float, no_match_pct: float, noisy_pct: float, ambiguous_pct: float,
                           duplicate_pct: float, seed: int = 7, store_ground_truth: bool = True,
                           run_now: bool = False, actor: str = "user") -> IncomingGenerationSummary:
    init_db()
    with get_session() as session:
        repo.ensure_defaults(session)
        masters = repo.load_master_records(session)
        gen: GenerationResult = generate_incoming(masters, n, match_pct, no_match_pct, noisy_pct, ambiguous_pct,
                                                  duplicate_pct, seed=seed, next_entity_index=repo.next_entity_index(session))
        if gen.new_master_records:
            repo.insert_master_records(session, gen.new_master_records, actor, action="DATA_GENERATED")
        batch_id = repo.next_batch_id(session, "GEN")
        ids = repo.insert_incoming_records(session, gen.records, batch_id, source="generator", actor=actor)
        labels = 0
        if store_ground_truth:
            rows = [{"incoming_id": ids[t["row"]], "true_entity_id": t["true_entity_id"], "true_decision": t["true_decision"]}
                    for t in gen.ground_truth]
            labels = repo.upsert_ground_truth(session, rows, source="generator", actor=actor)
    summary = IncomingGenerationSummary(batch_id=batch_id, records=len(gen.records), scenario_counts=gen.scenario_counts,
                                        twins_added=len(gen.new_master_records), ground_truth_labels=labels)
    if run_now:
        summary.run_id = run_batch(batch_id, actor=actor).run_id
    return summary


# -------------------------------------------------------------- matching
@dataclass
class RunSummary:
    run_id: str
    batch_id: str
    version: str
    records: int
    counts: dict
    duration_ms: float
    outcomes: list[MatchOutcome]
    incoming_ids: list[str]


def run_batch(batch_id: str, cfg: AlgorithmConfig | None = None, index: BlockingIndex | None = None,
              run_type: str = "batch", actor: str = "user") -> RunSummary:
    """Run the full pipeline on a stored batch and persist everything."""
    init_db()
    with get_session() as session:
        cfg = cfg or repo.get_active_config(session)
        records = repo.get_incoming_by_batch(session, batch_id)
        if not records:
            raise ValueError(f"Batch {batch_id} has no records.")
        index = index or BlockingIndex(repo.load_master_records(session))
        engine = MatchEngine(cfg, index)
        start = time.perf_counter()
        outcomes = engine.match_many(records)
        duration = round((time.perf_counter() - start) * 1000, 1)
        ids = [r["incoming_id"] for r in records]
        quality = data_quality_profile(pd.DataFrame([{f: r.get(f) for f in RECORD_FIELDS} for r in records]))
        run_id = repo.save_run(session, outcomes, ids, batch_id, cfg, run_type=run_type, duration_ms=duration,
                               data_quality=quality, actor=actor)
    counts = {"MATCH": 0, "MANUAL_REVIEW": 0, "NO_MATCH": 0}
    for o in outcomes:
        counts[o.decision] += 1
    log.info("Run %s: %s records, %s", run_id, len(outcomes), counts)
    return RunSummary(run_id=run_id, batch_id=batch_id, version=cfg.version_name, records=len(outcomes), counts=counts,
                      duration_ms=duration, outcomes=outcomes, incoming_ids=ids)


def store_upload_and_run(records: list[dict], filename: str, cfg: AlgorithmConfig | None = None,
                         index: BlockingIndex | None = None, actor: str = "user") -> RunSummary:
    """Persist uploaded rows as a batch, then match them."""
    init_db()
    with get_session() as session:
        repo.ensure_defaults(session)
        batch_id = repo.next_batch_id(session, "UPL")
        repo.insert_incoming_records(session, records, batch_id, source=f"upload:{filename}", actor=actor, action="FILE_UPLOADED")
    return run_batch(batch_id, cfg=cfg, index=index, run_type="upload", actor=actor)
