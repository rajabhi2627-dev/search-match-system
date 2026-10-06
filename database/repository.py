"""Repository – every database read/write used by the app lives here.

Keeping all SQL in one module means:
* the matching engine stays database-free (easy to test),
* the dashboard pages stay thin (they call functions, not queries),
* the audit log is written consistently from one place.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from database.models import (
    AlgorithmVersion, AuditLog, GroundTruth, HumanReview, IncomingRecord, MasterEntity, MatchCandidate,
    MatchResult, MergeHistory, MonitoringThreshold, PerformanceRun,
)
from matching.algorithm_config import AlgorithmConfig
from matching.merge_engine import build_merged_record, changed_fields
from matching.types import MatchOutcome
from performance.metrics import run_summary
from utils.helpers import RECORD_FIELDS, json_dumps, json_loads, load_config, now

DISPUTE_DECISIONS = {"REJECT_MATCH", "MARK_NO_MATCH", "SELECT_DIFFERENT_ENTITY"}


# =========================================================================
# Audit
# =========================================================================
def log_audit(session: Session, action_type: str, actor: str = "system", record_ref: str | None = None,
              algorithm_version: str | None = None, old_value=None, new_value=None, details: str | None = None) -> None:
    session.add(AuditLog(
        timestamp=now(), actor=actor, action_type=action_type, record_ref=record_ref,
        algorithm_version=algorithm_version,
        old_value=None if old_value is None else (old_value if isinstance(old_value, str) else json_dumps(old_value)),
        new_value=None if new_value is None else (new_value if isinstance(new_value, str) else json_dumps(new_value)),
        details=details,
    ))


def audit_logs(session: Session, limit: int = 500, action_type: str | None = None) -> pd.DataFrame:
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.log_id.desc()).limit(limit)
    if action_type:
        stmt = stmt.where(AuditLog.action_type == action_type)
    rows = session.scalars(stmt).all()
    return pd.DataFrame([{
        "Timestamp": r.timestamp, "Actor": r.actor, "Action Type": r.action_type, "Record": r.record_ref,
        "Algorithm Version": r.algorithm_version, "Old Value": r.old_value, "New Value": r.new_value, "Details": r.details,
    } for r in rows])


def audit_action_types(session: Session) -> list[str]:
    return [r for r in session.scalars(select(AuditLog.action_type).distinct()).all()]


# =========================================================================
# Algorithm versions
# =========================================================================
def _version_row(cfg: AlgorithmConfig, description: str, active: bool) -> AlgorithmVersion:
    return AlgorithmVersion(
        version_name=cfg.version_name,
        name_weight=cfg.weights["name"], email_weight=cfg.weights["email"], phone_weight=cfg.weights["phone"],
        address_weight=cfg.weights["address"], dob_weight=cfg.weights["dob"], company_weight=cfg.weights["company"],
        match_threshold=cfg.match_threshold, manual_review_threshold=cfg.manual_review_threshold,
        ambiguity_gap_threshold=cfg.ambiguity_gap_threshold, blocking_rules=json_dumps(cfg.blocking_passes),
        rare_value_weighting=cfg.rare_value_weighting, top_n=cfg.top_n, created_at=now(),
        description=description, is_active=active,
    )


def list_versions(session: Session) -> list[AlgorithmVersion]:
    return list(session.scalars(select(AlgorithmVersion).order_by(AlgorithmVersion.version_id)).all())


def get_version(session: Session, version_name: str) -> AlgorithmVersion | None:
    return session.scalar(select(AlgorithmVersion).where(AlgorithmVersion.version_name == version_name))


def get_active_version(session: Session) -> AlgorithmVersion:
    row = session.scalar(select(AlgorithmVersion).where(AlgorithmVersion.is_active.is_(True)))
    if row is None:
        ensure_defaults(session)
        row = session.scalar(select(AlgorithmVersion).where(AlgorithmVersion.is_active.is_(True)))
    return row


def get_active_config(session: Session) -> AlgorithmConfig:
    return AlgorithmConfig.from_db_row(get_active_version(session))


def next_version_name(session: Session) -> str:
    names = [v.version_name for v in list_versions(session)]
    best = (1, 0)
    for n in names:
        try:
            major, minor = n.split(".")[:2]
            best = max(best, (int(major), int(minor)))
        except ValueError:
            continue
    return f"{best[0]}.{best[1] + 1}"


def create_version(session: Session, cfg: AlgorithmConfig, description: str, activate: bool = True,
                   actor: str = "user") -> AlgorithmVersion:
    problems = cfg.validate()
    if problems:
        raise ValueError("; ".join(problems))
    if get_version(session, cfg.version_name):
        raise ValueError(f"Version {cfg.version_name} already exists. Versions are never overwritten.")
    previous = session.scalar(select(AlgorithmVersion).where(AlgorithmVersion.is_active.is_(True)))
    if activate:
        for v in list_versions(session):
            v.is_active = False
    row = _version_row(cfg, description, activate)
    session.add(row)
    log_audit(session, "ALGORITHM_CREATED", actor, record_ref=f"v{cfg.version_name}", algorithm_version=cfg.version_name,
              old_value=AlgorithmConfig.from_db_row(previous).signature() if previous else None,
              new_value=cfg.signature(), details=description)
    session.flush()
    return row


def activate_version(session: Session, version_name: str, actor: str = "user") -> None:
    current = get_active_version(session)
    for v in list_versions(session):
        v.is_active = v.version_name == version_name
    log_audit(session, "ALGORITHM_ACTIVATED", actor, record_ref=f"v{version_name}", algorithm_version=version_name,
              old_value=current.version_name if current else None, new_value=version_name)


def versions_frame(session: Session) -> pd.DataFrame:
    rows = []
    for v in list_versions(session):
        rows.append({
            "Version": v.version_name, "Active": "✅" if v.is_active else "", "Created": v.created_at,
            "Name %": v.name_weight, "Email %": v.email_weight, "Phone %": v.phone_weight, "Address %": v.address_weight,
            "DOB %": v.dob_weight, "Company %": v.company_weight, "Match ≥": v.match_threshold,
            "Review ≥": v.manual_review_threshold, "Gap ≥": v.ambiguity_gap_threshold,
            "Blocking passes": ", ".join(json_loads(v.blocking_rules, [])), "Rare-value": "ON" if v.rare_value_weighting else "OFF",
            "Top-N": v.top_n, "Description": v.description,
        })
    return pd.DataFrame(rows)


# =========================================================================
# Defaults
# =========================================================================
def ensure_defaults(session: Session) -> None:
    """Create algorithm version 1.0 and the monitoring thresholds if missing."""
    if session.scalar(select(func.count()).select_from(AlgorithmVersion)) == 0:
        cfg = AlgorithmConfig.from_yaml()
        session.add(_version_row(cfg, cfg.description or "Baseline prototype configuration", True))
        log_audit(session, "ALGORITHM_CREATED", "system", record_ref=f"v{cfg.version_name}",
                  algorithm_version=cfg.version_name, new_value=cfg.signature(), details="Initial version from config.yaml")
    if session.scalar(select(func.count()).select_from(MonitoringThreshold)) == 0:
        for t in load_config().get("monitoring_thresholds", []):
            session.add(MonitoringThreshold(metric=t["metric"], label=t["label"], direction=t["direction"],
                                            green=float(t["green"]), amber=float(t["amber"]), updated_at=now()))


# =========================================================================
# Master data
# =========================================================================
def master_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(MasterEntity)) or 0


def master_fingerprint(session: Session) -> tuple:
    """Cheap token that changes whenever the master data changes (for caching)."""
    count = master_count(session)
    latest = session.scalar(select(func.max(MasterEntity.updated_at)))
    last_id = session.scalar(select(func.max(MasterEntity.entity_id)))
    return (count, str(latest), last_id)


def load_master_records(session: Session) -> list[dict]:
    return [r.to_dict() for r in session.scalars(select(MasterEntity).order_by(MasterEntity.entity_id)).all()]


def master_frame(session: Session, limit: int | None = None) -> pd.DataFrame:
    stmt = select(MasterEntity).order_by(MasterEntity.entity_id)
    if limit:
        stmt = stmt.limit(limit)
    return pd.DataFrame([r.to_dict() | {"source": r.source} for r in session.scalars(stmt).all()])


def get_master(session: Session, entity_id: str) -> MasterEntity | None:
    return session.get(MasterEntity, entity_id)


def next_entity_index(session: Session) -> int:
    last = session.scalar(select(func.max(MasterEntity.entity_id)))
    return int(last[1:]) + 1 if last else 1


def insert_master_records(session: Session, records: list[dict], actor: str = "user", action: str = "DATA_GENERATED") -> int:
    ts = now()
    session.bulk_insert_mappings(MasterEntity, [{
        **{f: r.get(f) for f in RECORD_FIELDS}, "entity_id": r["entity_id"],
        "source": r.get("source", "synthetic"), "created_at": ts, "updated_at": ts,
    } for r in records])
    log_audit(session, action, actor, record_ref="master_entities", new_value={"records": len(records)},
              details=f"{len(records)} master records inserted")
    return len(records)


def clear_master_and_dependents(session: Session, actor: str = "user") -> None:
    """Delete master data AND everything derived from it (incoming, results, runs, reviews, merges, labels)."""
    for model in (MergeHistory, HumanReview, MatchCandidate, MatchResult, PerformanceRun, GroundTruth, IncomingRecord, MasterEntity):
        session.execute(delete(model))
    log_audit(session, "DATA_CLEARED", actor, record_ref="all", details="Master data and all dependent tables cleared")


def clear_incoming_and_results(session: Session, actor: str = "user") -> None:
    for model in (MergeHistory, HumanReview, MatchCandidate, MatchResult, PerformanceRun, GroundTruth, IncomingRecord):
        session.execute(delete(model))
    log_audit(session, "DATA_CLEARED", actor, record_ref="incoming", details="Incoming data, results and runs cleared")


# =========================================================================
# Incoming data & batches
# =========================================================================
def next_batch_id(session: Session, prefix: str = "B") -> str:
    count = session.scalar(select(func.count(func.distinct(IncomingRecord.batch_id)))) or 0
    return f"{prefix}{count + 1:04d}"


def insert_incoming_records(session: Session, records: list[dict], batch_id: str, source: str,
                            actor: str = "user", action: str = "DATA_GENERATED") -> list[str]:
    """Insert records and return their incoming_ids (in input order)."""
    start = (session.scalar(select(func.count()).select_from(IncomingRecord)) or 0) + 1
    ts = now()
    ids = []
    mappings = []
    for i, r in enumerate(records):
        iid = f"I{start + i:06d}"
        ids.append(iid)
        mappings.append({
            "incoming_id": iid, **{f: r.get(f) for f in RECORD_FIELDS}, "received_at": ts,
            "source": source, "batch_id": batch_id, "scenario": r.get("scenario"),
        })
    session.bulk_insert_mappings(IncomingRecord, mappings)
    log_audit(session, action, actor, record_ref=batch_id, new_value={"records": len(records), "source": source},
              details=f"Batch {batch_id}: {len(records)} incoming records ({source})")
    return ids


def list_batches(session: Session) -> pd.DataFrame:
    stmt = (
        select(IncomingRecord.batch_id, IncomingRecord.source, func.count().label("records"),
               func.min(IncomingRecord.received_at).label("received_at"))
        .group_by(IncomingRecord.batch_id, IncomingRecord.source)
        .order_by(func.min(IncomingRecord.received_at).desc())
    )
    rows = session.execute(stmt).all()
    df = pd.DataFrame([{"batch_id": r.batch_id, "source": r.source, "records": r.records, "received_at": r.received_at} for r in rows])
    if df.empty:
        return df
    runs = session.execute(select(PerformanceRun.batch_id, func.count().label("runs")).group_by(PerformanceRun.batch_id)).all()
    run_map = {r.batch_id: r.runs for r in runs}
    df["runs"] = df["batch_id"].map(run_map).fillna(0).astype(int)
    return df


def get_incoming_by_batch(session: Session, batch_id: str) -> list[dict]:
    rows = session.scalars(select(IncomingRecord).where(IncomingRecord.batch_id == batch_id).order_by(IncomingRecord.incoming_id)).all()
    return [r.to_dict() for r in rows]


def get_incoming(session: Session, incoming_id: str) -> IncomingRecord | None:
    return session.get(IncomingRecord, incoming_id)


def incoming_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(IncomingRecord)) or 0


# =========================================================================
# Ground truth
# =========================================================================
def upsert_ground_truth(session: Session, rows: list[dict], source: str, actor: str = "user") -> int:
    existing = {g.incoming_id: g for g in session.scalars(select(GroundTruth).where(
        GroundTruth.incoming_id.in_([r["incoming_id"] for r in rows]))).all()} if rows else {}
    for r in rows:
        if r["incoming_id"] in existing:
            g = existing[r["incoming_id"]]
            g.true_entity_id, g.true_decision, g.source = r.get("true_entity_id"), r["true_decision"], source
        else:
            session.add(GroundTruth(incoming_id=r["incoming_id"], true_entity_id=r.get("true_entity_id"),
                                    true_decision=r["true_decision"], source=source, created_at=now()))
    log_audit(session, "GROUND_TRUTH_LOADED", actor, record_ref=source, new_value={"labels": len(rows)},
              details=f"{len(rows)} ground-truth labels ({source})")
    return len(rows)


def get_ground_truth(session: Session, incoming_ids: list[str] | None = None) -> dict[str, dict]:
    stmt = select(GroundTruth)
    if incoming_ids is not None:
        if not incoming_ids:
            return {}
        stmt = stmt.where(GroundTruth.incoming_id.in_(incoming_ids))
    return {g.incoming_id: {"true_entity_id": g.true_entity_id, "true_decision": g.true_decision, "source": g.source}
            for g in session.scalars(stmt).all()}


def ground_truth_frame(session: Session) -> pd.DataFrame:
    rows = session.scalars(select(GroundTruth).order_by(GroundTruth.incoming_id)).all()
    return pd.DataFrame([{"incoming_id": g.incoming_id, "true_entity_id": g.true_entity_id,
                          "true_decision": g.true_decision, "source": g.source} for g in rows])


def ground_truth_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(GroundTruth)) or 0


# =========================================================================
# Runs, results, candidates
# =========================================================================
def next_run_id(session: Session) -> str:
    count = session.scalar(select(func.count()).select_from(PerformanceRun)) or 0
    return f"R{count + 1:04d}"


def save_run(session: Session, outcomes: list[MatchOutcome], incoming_ids: list[str], batch_id: str,
             cfg: AlgorithmConfig, run_type: str = "batch", duration_ms: float | None = None,
             data_quality: dict | None = None, actor: str = "user") -> str:
    """Persist results + candidates + the performance_runs row. Returns run_id."""
    run_id = next_run_id(session)
    ts = now()
    result_rows, cand_rows = [], []
    for iid, o in zip(incoming_ids, outcomes):
        result_rows.append({
            "run_id": run_id, "batch_id": batch_id, "incoming_id": iid, "entity_id": o.best_entity_id,
            "overall_score": o.best_score, "score_gap": o.score_gap, "decision": o.decision, "confidence": o.confidence,
            "conflict_flag": o.conflict_flag, "reason": o.reason, "decision_rule": o.decision_rule,
            "candidate_pool_size": o.pool_size, "master_size": o.master_size,
            "details_json": json_dumps({"set_conflicts": o.set_conflicts, "confidence_factors": o.confidence_factors,
                                        "confidence_points": o.confidence_points, "blocking_passes": o.blocking_passes_used,
                                        "duration_ms": o.duration_ms}),
            "algorithm_version": cfg.version_name, "matched_at": ts,
        })
        for c in o.candidates:
            cand_rows.append({
                "run_id": run_id, "incoming_id": iid, "entity_id": c.entity_id, "candidate_rank": c.rank,
                "name_score": c.field_scores.get("name"), "email_score": c.field_scores.get("email"),
                "phone_score": c.field_scores.get("phone"), "address_score": c.field_scores.get("address"),
                "dob_score": c.field_scores.get("dob"), "company_score": c.field_scores.get("company"),
                "overall_score": c.overall, "score_gap": c.gap_to_next, "conflict_flag": c.conflict_flag,
                "critical_conflict": c.critical_conflict, "confidence": c.confidence, "decision": c.decision,
                "blocking_methods": json_dumps(c.blocking_methods), "exact_rules": json_dumps(c.exact_rules),
                "details_json": json_dumps({"field_details": c.field_details, "breakdown": c.breakdown,
                                            "conflicts": c.conflicts, "confidence_factors": c.confidence_factors,
                                            "confidence_points": c.confidence_points, "master": c.master}),
                "algorithm_version": cfg.version_name, "created_at": ts,
            })
    if result_rows:
        session.bulk_insert_mappings(MatchResult, result_rows)
    if cand_rows:
        session.bulk_insert_mappings(MatchCandidate, cand_rows)

    session.add(PerformanceRun(run_id=run_id, batch_id=batch_id, algorithm_version=cfg.version_name, timestamp=ts,
                               run_type=run_type, duration_ms=duration_ms,
                               data_quality_json=json_dumps(data_quality) if data_quality else None))
    session.flush()
    recompute_run_metrics(session, run_id)
    log_audit(session, "MATCH_RUN", actor, record_ref=run_id, algorithm_version=cfg.version_name,
              new_value={"batch_id": batch_id, "records": len(outcomes)},
              details=f"Run {run_id} on batch {batch_id} with v{cfg.version_name} ({len(outcomes)} records)")
    return run_id


def get_run(session: Session, run_id: str) -> PerformanceRun | None:
    return session.get(PerformanceRun, run_id)


def list_runs(session: Session) -> list[PerformanceRun]:
    return list(session.scalars(select(PerformanceRun).order_by(PerformanceRun.timestamp, PerformanceRun.run_id)).all())


def runs_frame(session: Session) -> pd.DataFrame:
    rows = []
    for r in list_runs(session):
        rows.append({
            "run_id": r.run_id, "batch_id": r.batch_id, "algorithm_version": r.algorithm_version, "timestamp": r.timestamp,
            "run_type": r.run_type, "total_records": r.total_records, "total_matches": r.total_matches,
            "total_manual_reviews": r.total_manual_reviews, "total_no_matches": r.total_no_matches,
            "match_rate": r.match_rate, "hit_rate": r.hit_rate, "precision": r.precision, "recall": r.recall,
            "f1_score": r.f1_score, "accuracy": r.accuracy, "false_positive_rate": r.false_positive_rate,
            "false_negative_rate": r.false_negative_rate, "manual_review_rate": r.manual_review_rate,
            "dispute_rate": r.dispute_rate, "merge_error_rate": r.merge_error_rate,
            "candidate_reduction_pct": r.candidate_reduction_pct, "avg_candidates": r.avg_candidates,
            "ground_truth_available": r.ground_truth_available, "tp": r.tp, "fp": r.fp, "fn": r.fn, "tn": r.tn,
            "duration_ms": r.duration_ms, "data_quality": json_loads(r.data_quality_json, {}),
        })
    return pd.DataFrame(rows)


def get_results(session: Session, run_id: str) -> list[dict]:
    rows = session.scalars(select(MatchResult).where(MatchResult.run_id == run_id).order_by(MatchResult.incoming_id)).all()
    return [_result_dict(r) for r in rows]


def _result_dict(r: MatchResult) -> dict:
    return {
        "match_id": r.match_id, "run_id": r.run_id, "batch_id": r.batch_id, "incoming_id": r.incoming_id,
        "entity_id": r.entity_id, "overall_score": r.overall_score, "score_gap": r.score_gap, "decision": r.decision,
        "confidence": r.confidence, "conflict_flag": r.conflict_flag, "reason": r.reason, "decision_rule": r.decision_rule,
        "candidate_pool_size": r.candidate_pool_size, "master_size": r.master_size,
        "algorithm_version": r.algorithm_version, "matched_at": r.matched_at, "details": json_loads(r.details_json, {}),
    }


def results_frame(session: Session, run_id: str) -> pd.DataFrame:
    """Results joined with incoming names + best candidate names for display."""
    results = get_results(session, run_id)
    if not results:
        return pd.DataFrame()
    incoming = {r.incoming_id: r for r in session.scalars(select(IncomingRecord).where(
        IncomingRecord.incoming_id.in_([x["incoming_id"] for x in results]))).all()}
    entity_ids = [x["entity_id"] for x in results if x["entity_id"]]
    masters = {m.entity_id: m.name for m in session.scalars(select(MasterEntity).where(MasterEntity.entity_id.in_(entity_ids))).all()} if entity_ids else {}
    truth = get_ground_truth(session, [x["incoming_id"] for x in results])
    rows = []
    for i, x in enumerate(results, start=1):
        inc = incoming.get(x["incoming_id"])
        t = truth.get(x["incoming_id"])
        rows.append({
            "Row": i, "Incoming ID": x["incoming_id"], "Incoming Name": inc.name if inc else "", "Scenario": inc.scenario if inc else "",
            "Best Candidate": masters.get(x["entity_id"], "-") if x["entity_id"] else "-", "Entity ID": x["entity_id"] or "-",
            "Overall Score": x["overall_score"], "Score Gap": x["score_gap"], "Confidence": x["confidence"],
            "Conflict": "Yes" if x["conflict_flag"] else "No", "Decision": x["decision"], "Reason": x["reason"],
            "True Entity": (t or {}).get("true_entity_id") or ("-" if t else ""), "True Decision": (t or {}).get("true_decision") or "",
            "Candidates": x["candidate_pool_size"], "match_id": x["match_id"],
        })
    return pd.DataFrame(rows)


def get_result(session: Session, match_id: int) -> dict | None:
    r = session.get(MatchResult, match_id)
    return _result_dict(r) if r else None


def get_candidates(session: Session, run_id: str, incoming_id: str) -> list[dict]:
    rows = session.scalars(select(MatchCandidate).where(MatchCandidate.run_id == run_id, MatchCandidate.incoming_id == incoming_id)
                           .order_by(MatchCandidate.candidate_rank)).all()
    out = []
    for c in rows:
        details = json_loads(c.details_json, {})
        out.append({
            "entity_id": c.entity_id, "rank": c.candidate_rank, "overall": c.overall_score, "gap_to_next": c.score_gap,
            "field_scores": {"name": c.name_score, "email": c.email_score, "phone": c.phone_score,
                             "address": c.address_score, "dob": c.dob_score, "company": c.company_score},
            "conflict_flag": c.conflict_flag, "critical_conflict": c.critical_conflict, "confidence": c.confidence,
            "decision": c.decision, "blocking_methods": json_loads(c.blocking_methods, []),
            "exact_rules": json_loads(c.exact_rules, []), **details,
        })
    return out


def candidates_by_incoming(session: Session, run_id: str) -> dict[str, list[str]]:
    rows = session.execute(select(MatchCandidate.incoming_id, MatchCandidate.entity_id)
                           .where(MatchCandidate.run_id == run_id)).all()
    out: dict[str, list[str]] = {}
    for iid, eid in rows:
        out.setdefault(iid, []).append(eid)
    return out


def latest_run_id(session: Session) -> str | None:
    r = session.scalar(select(PerformanceRun).order_by(PerformanceRun.timestamp.desc(), PerformanceRun.run_id.desc()))
    return r.run_id if r else None


# =========================================================================
# Metrics recomputation (keeps performance_runs honest after reviews/merges)
# =========================================================================
def recompute_run_metrics(session: Session, run_id: str) -> None:
    run = session.get(PerformanceRun, run_id)
    if run is None:
        return
    results = get_results(session, run_id)
    version = get_version(session, run.algorithm_version)
    threshold = version.manual_review_threshold if version else 65.0
    truth = get_ground_truth(session, [r["incoming_id"] for r in results])
    cands = candidates_by_incoming(session, run_id)

    reviews = session.scalars(select(HumanReview).where(HumanReview.run_id == run_id)).all()
    disputes = sum(1 for r in reviews if r.is_dispute)
    merges = session.scalars(select(MergeHistory).where(MergeHistory.run_id == run_id)).all()
    confirmed = [m for m in merges if m.merge_decision == "CONFIRMED"]
    reversed_ids = {m.match_id for m in merges if m.merge_decision == "REVERSED"}
    disputes += len(reversed_ids)
    incorrect = 0
    for m in confirmed:
        wrong = m.is_error or m.match_id in reversed_ids
        t = truth.get(m.incoming_id)
        if t and ((t["true_decision"] == "NO_MATCH") or (t["true_entity_id"] and t["true_entity_id"] != m.entity_id)):
            wrong = True
        incorrect += int(bool(wrong))

    s = run_summary(results, threshold, truth, cands, disputes=disputes, total_merges=len(confirmed), incorrect_merges=incorrect)
    run.total_records, run.total_matches = s["total_records"], s["total_matches"]
    run.total_manual_reviews, run.total_no_matches = s["total_manual_reviews"], s["total_no_matches"]
    run.match_rate, run.hit_rate, run.manual_review_rate = s["match_rate"], s["hit_rate"], s["manual_review_rate"]
    run.precision, run.recall, run.f1_score, run.accuracy = s["precision"], s["recall"], s["f1_score"], s["accuracy"]
    run.false_positive_rate, run.false_negative_rate = s["false_positive_rate"], s["false_negative_rate"]
    run.dispute_rate, run.merge_error_rate = s["dispute_rate"], s["merge_error_rate"]
    run.candidate_reduction_pct, run.avg_candidates = s["candidate_reduction_pct"], s["avg_candidates"]
    run.ground_truth_available = s["ground_truth_available"]
    run.tp, run.fp, run.fn, run.tn = s["tp"], s["fp"], s["fn"], s["tn"]


def recompute_all_runs(session: Session) -> int:
    runs = list_runs(session)
    for r in runs:
        recompute_run_metrics(session, r.run_id)
    return len(runs)


# =========================================================================
# Human review
# =========================================================================
def add_review(session: Session, result: dict, review_decision: str, reviewer: str, reason: str,
               actual_entity_id: str | None = None) -> HumanReview:
    predicted_match = result["decision"] == "MATCH"
    if review_decision == "CONFIRM_MATCH":
        actual = result["entity_id"]
    elif review_decision == "SELECT_DIFFERENT_ENTITY":
        actual = actual_entity_id
    else:
        actual = None
    is_dispute = predicted_match and review_decision in DISPUTE_DECISIONS
    row = HumanReview(run_id=result["run_id"], match_id=result["match_id"], incoming_id=result["incoming_id"],
                      predicted_entity_id=result["entity_id"], predicted_decision=result["decision"],
                      actual_entity_id=actual, review_decision=review_decision, review_reason=reason,
                      reviewer=reviewer, is_dispute=is_dispute, timestamp=now())
    session.add(row)
    # a confirmed human decision becomes ground truth for this record
    if review_decision in ("CONFIRM_MATCH", "SELECT_DIFFERENT_ENTITY") and actual:
        upsert_ground_truth(session, [{"incoming_id": result["incoming_id"], "true_entity_id": actual, "true_decision": "MATCH"}],
                            source="human_review", actor=reviewer)
    elif review_decision == "MARK_NO_MATCH":
        upsert_ground_truth(session, [{"incoming_id": result["incoming_id"], "true_entity_id": None, "true_decision": "NO_MATCH"}],
                            source="human_review", actor=reviewer)
    # if a confirmed merge exists for this record and the reviewer disagrees, flag it as a merge error
    if review_decision in DISPUTE_DECISIONS:
        for m in session.scalars(select(MergeHistory).where(MergeHistory.match_id == result["match_id"],
                                                             MergeHistory.merge_decision == "CONFIRMED")).all():
            m.is_error = True
    log_audit(session, "MANUAL_REVIEW", reviewer, record_ref=result["incoming_id"], algorithm_version=result["algorithm_version"],
              old_value={"decision": result["decision"], "entity_id": result["entity_id"]},
              new_value={"review": review_decision, "entity_id": actual}, details=reason)
    session.flush()
    recompute_run_metrics(session, result["run_id"])
    return row


def reviews_frame(session: Session, run_id: str | None = None) -> pd.DataFrame:
    stmt = select(HumanReview).order_by(HumanReview.timestamp.desc())
    if run_id:
        stmt = stmt.where(HumanReview.run_id == run_id)
    rows = session.scalars(stmt).all()
    return pd.DataFrame([{
        "Review ID": r.review_id, "Run": r.run_id, "Incoming ID": r.incoming_id, "Predicted Entity": r.predicted_entity_id,
        "Predicted Decision": r.predicted_decision, "Reviewer Decision": r.review_decision, "Actual Entity": r.actual_entity_id,
        "Dispute": "Yes" if r.is_dispute else "No", "Reviewer": r.reviewer, "Reason": r.review_reason, "Timestamp": r.timestamp,
    } for r in rows])


def reviewed_match_ids(session: Session, run_id: str) -> set[int]:
    return set(session.scalars(select(HumanReview.match_id).where(HumanReview.run_id == run_id)).all())


# =========================================================================
# Merge
# =========================================================================
def confirm_merge(session: Session, result: dict, choices: dict[str, str], reason: str, actor: str) -> MergeHistory:
    master = session.get(MasterEntity, result["entity_id"])
    incoming = session.get(IncomingRecord, result["incoming_id"])
    if master is None or incoming is None:
        raise ValueError("Master or incoming record not found.")
    old = master.to_dict()
    merged = build_merged_record(old, incoming.to_dict(), choices)
    changes = changed_fields(old, merged)
    for f, change in changes.items():
        setattr(master, f, change["new"])
    master.updated_at = now()
    row = MergeHistory(run_id=result["run_id"], match_id=result["match_id"], incoming_id=result["incoming_id"],
                       entity_id=result["entity_id"], merge_decision="CONFIRMED", merge_timestamp=now(),
                       algorithm_version=result["algorithm_version"], reason=reason, old_values=json_dumps(old),
                       new_values=json_dumps(merged), actor=actor)
    session.add(row)
    log_audit(session, "MERGE_CONFIRMED", actor, record_ref=f"{result['incoming_id']}→{result['entity_id']}",
              algorithm_version=result["algorithm_version"], old_value=old, new_value=merged,
              details=f"{len(changes)} field(s) changed: {', '.join(changes) if changes else 'none'}")
    session.flush()
    recompute_run_metrics(session, result["run_id"])
    return row


def reject_merge(session: Session, result: dict, reason: str, actor: str) -> MergeHistory:
    row = MergeHistory(run_id=result["run_id"], match_id=result["match_id"], incoming_id=result["incoming_id"],
                       entity_id=result["entity_id"], merge_decision="REJECTED", merge_timestamp=now(),
                       algorithm_version=result["algorithm_version"], reason=reason, actor=actor)
    session.add(row)
    # rejecting an algorithm MATCH is a dispute → record as a review too
    if result["decision"] == "MATCH":
        session.add(HumanReview(run_id=result["run_id"], match_id=result["match_id"], incoming_id=result["incoming_id"],
                                predicted_entity_id=result["entity_id"], predicted_decision=result["decision"],
                                actual_entity_id=None, review_decision="REJECT_MATCH", review_reason=f"Merge rejected: {reason}",
                                reviewer=actor, is_dispute=True, timestamp=now()))
    log_audit(session, "MERGE_REJECTED", actor, record_ref=f"{result['incoming_id']}→{result['entity_id']}",
              algorithm_version=result["algorithm_version"], details=reason)
    session.flush()
    recompute_run_metrics(session, result["run_id"])
    return row


def reverse_merge(session: Session, merge_id: int, reason: str, actor: str) -> None:
    m = session.get(MergeHistory, merge_id)
    if m is None or m.merge_decision != "CONFIRMED":
        raise ValueError("Only confirmed merges can be reversed.")
    master = session.get(MasterEntity, m.entity_id)
    old = json_loads(m.old_values, {})
    if master and old:
        for f in RECORD_FIELDS:
            setattr(master, f, old.get(f))
        master.updated_at = now()
    m.is_error = True
    session.add(MergeHistory(run_id=m.run_id, match_id=m.match_id, incoming_id=m.incoming_id, entity_id=m.entity_id,
                             merge_decision="REVERSED", merge_timestamp=now(), algorithm_version=m.algorithm_version,
                             reason=reason, old_values=m.new_values, new_values=m.old_values, actor=actor))
    log_audit(session, "MERGE_REVERSED", actor, record_ref=f"{m.incoming_id}→{m.entity_id}",
              algorithm_version=m.algorithm_version, old_value=json_loads(m.new_values, {}), new_value=old, details=reason)
    session.flush()
    if m.run_id:
        recompute_run_metrics(session, m.run_id)


def merges_frame(session: Session, run_id: str | None = None) -> pd.DataFrame:
    stmt = select(MergeHistory).order_by(MergeHistory.merge_timestamp.desc())
    if run_id:
        stmt = stmt.where(MergeHistory.run_id == run_id)
    rows = session.scalars(stmt).all()
    return pd.DataFrame([{
        "Merge ID": m.merge_id, "Run": m.run_id, "Incoming ID": m.incoming_id, "Entity ID": m.entity_id,
        "Action": m.merge_decision, "Error": "Yes" if m.is_error else "No", "Timestamp": m.merge_timestamp,
        "Version": m.algorithm_version, "Reason": m.reason, "Actor": m.actor,
        "Old Values": m.old_values, "New Values": m.new_values,
    } for m in rows])


def merged_match_ids(session: Session, run_id: str) -> set[int]:
    return set(session.scalars(select(MergeHistory.match_id).where(MergeHistory.run_id == run_id)).all())


def confirmed_merges(session: Session) -> list[MergeHistory]:
    return list(session.scalars(select(MergeHistory).where(MergeHistory.merge_decision == "CONFIRMED")
                                .order_by(MergeHistory.merge_timestamp.desc())).all())


# =========================================================================
# Monitoring thresholds
# =========================================================================
def get_thresholds(session: Session) -> list[MonitoringThreshold]:
    return list(session.scalars(select(MonitoringThreshold)).all())


def update_threshold(session: Session, metric: str, green: float, amber: float, actor: str = "user") -> None:
    t = session.get(MonitoringThreshold, metric)
    if t is None:
        return
    old = {"green": t.green, "amber": t.amber}
    if old["green"] == green and old["amber"] == amber:
        return
    t.green, t.amber, t.updated_at = green, amber, now()
    log_audit(session, "THRESHOLD_CHANGED", actor, record_ref=metric, old_value=old, new_value={"green": green, "amber": amber},
              details=f"Monitoring threshold for {t.label} changed")


# =========================================================================
# Summary counts for the dashboard
# =========================================================================
def counts_summary(session: Session) -> dict:
    return {
        "master": master_count(session),
        "incoming": incoming_count(session),
        "runs": session.scalar(select(func.count()).select_from(PerformanceRun)) or 0,
        "reviews": session.scalar(select(func.count()).select_from(HumanReview)) or 0,
        "merges": session.scalar(select(func.count()).select_from(MergeHistory).where(MergeHistory.merge_decision == "CONFIRMED")) or 0,
        "ground_truth": ground_truth_count(session),
        "versions": session.scalar(select(func.count()).select_from(AlgorithmVersion)) or 0,
    }
