"""SQLAlchemy ORM models – one class per database table.

Tables A–I are the ones required by the project brief.  Two small support
tables (ground_truth, monitoring_thresholds) are added so that labelled data
and Green/Amber/Red thresholds are also stored in the database.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# A. master_entities – the "golden" customer database we search against
# ---------------------------------------------------------------------------
class MasterEntity(Base):
    __tablename__ = "master_entities"

    entity_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    date_of_birth: Mapped[str | None] = mapped_column(String(20))
    company: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(50), default="synthetic")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "date_of_birth": self.date_of_birth,
            "company": self.company,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
        }


# ---------------------------------------------------------------------------
# B. incoming_records – records that need to be matched to the master
# ---------------------------------------------------------------------------
class IncomingRecord(Base):
    __tablename__ = "incoming_records"

    incoming_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    date_of_birth: Mapped[str | None] = mapped_column(String(20))
    company: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    source: Mapped[str | None] = mapped_column(String(50))          # generator / upload / manual
    batch_id: Mapped[str | None] = mapped_column(String(40), index=True)
    scenario: Mapped[str | None] = mapped_column(String(60))        # generator scenario label (demo aid)

    def to_dict(self) -> dict:
        return {
            "incoming_id": self.incoming_id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "date_of_birth": self.date_of_birth,
            "company": self.company,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "batch_id": self.batch_id,
            "source": self.source,
            "scenario": self.scenario,
        }


# ---------------------------------------------------------------------------
# C. match_candidates – every top-N candidate with component scores
# ---------------------------------------------------------------------------
class MatchCandidate(Base):
    __tablename__ = "match_candidates"

    candidate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(20), index=True)
    incoming_id: Mapped[str] = mapped_column(String(20), ForeignKey("incoming_records.incoming_id"), index=True)
    entity_id: Mapped[str] = mapped_column(String(20), index=True)
    candidate_rank: Mapped[int] = mapped_column(Integer)
    name_score: Mapped[float | None] = mapped_column(Float)
    email_score: Mapped[float | None] = mapped_column(Float)
    phone_score: Mapped[float | None] = mapped_column(Float)
    address_score: Mapped[float | None] = mapped_column(Float)
    dob_score: Mapped[float | None] = mapped_column(Float)
    company_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float] = mapped_column(Float)
    score_gap: Mapped[float | None] = mapped_column(Float)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str | None] = mapped_column(String(10))
    decision: Mapped[str | None] = mapped_column(String(20))
    blocking_methods: Mapped[str | None] = mapped_column(Text)      # JSON list
    exact_rules: Mapped[str | None] = mapped_column(Text)           # JSON list
    details_json: Mapped[str | None] = mapped_column(Text)          # JSON – full explanation payload
    algorithm_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# D. match_results – one final decision per incoming record per run
# ---------------------------------------------------------------------------
class MatchResult(Base):
    __tablename__ = "match_results"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(20), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(40), index=True)
    incoming_id: Mapped[str] = mapped_column(String(20), ForeignKey("incoming_records.incoming_id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(20), index=True)
    overall_score: Mapped[float | None] = mapped_column(Float)
    score_gap: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[str | None] = mapped_column(String(10))
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    decision_rule: Mapped[str | None] = mapped_column(String(40))
    candidate_pool_size: Mapped[int | None] = mapped_column(Integer)
    master_size: Mapped[int | None] = mapped_column(Integer)
    details_json: Mapped[str | None] = mapped_column(Text)          # JSON – set conflicts, confidence factors
    algorithm_version: Mapped[str | None] = mapped_column(String(20))
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# E. merge_history – every confirm / reject / reverse action
# ---------------------------------------------------------------------------
class MergeHistory(Base):
    __tablename__ = "merge_history"

    merge_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(20), index=True)
    match_id: Mapped[int | None] = mapped_column(Integer, index=True)
    incoming_id: Mapped[str] = mapped_column(String(20), index=True)
    entity_id: Mapped[str] = mapped_column(String(20), index=True)
    merge_decision: Mapped[str] = mapped_column(String(20))         # CONFIRMED / REJECTED / REVERSED
    merge_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    algorithm_version: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    old_values: Mapped[str | None] = mapped_column(Text)            # JSON
    new_values: Mapped[str | None] = mapped_column(Text)            # JSON
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)  # set when review / ground truth says merge was wrong
    actor: Mapped[str | None] = mapped_column(String(80))


# ---------------------------------------------------------------------------
# F. algorithm_versions – immutable record of every weight/threshold set
# ---------------------------------------------------------------------------
class AlgorithmVersion(Base):
    __tablename__ = "algorithm_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_name: Mapped[str] = mapped_column(String(20), unique=True)
    name_weight: Mapped[float] = mapped_column(Float)
    email_weight: Mapped[float] = mapped_column(Float)
    phone_weight: Mapped[float] = mapped_column(Float)
    address_weight: Mapped[float] = mapped_column(Float)
    dob_weight: Mapped[float] = mapped_column(Float)
    company_weight: Mapped[float] = mapped_column(Float)
    match_threshold: Mapped[float] = mapped_column(Float)
    manual_review_threshold: Mapped[float] = mapped_column(Float)
    ambiguity_gap_threshold: Mapped[float] = mapped_column(Float)
    blocking_rules: Mapped[str | None] = mapped_column(Text)        # JSON list of pass names
    rare_value_weighting: Mapped[bool] = mapped_column(Boolean, default=False)
    top_n: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# G. performance_runs – one row per matching run (batch × algorithm version)
# ---------------------------------------------------------------------------
class PerformanceRun(Base):
    __tablename__ = "performance_runs"

    run_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(String(40), index=True)
    algorithm_version: Mapped[str | None] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    run_type: Mapped[str | None] = mapped_column(String(30), default="batch")   # batch / upload / rerun
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    total_matches: Mapped[int] = mapped_column(Integer, default=0)
    total_no_matches: Mapped[int] = mapped_column(Integer, default=0)
    total_manual_reviews: Mapped[int] = mapped_column(Integer, default=0)
    match_rate: Mapped[float | None] = mapped_column(Float)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)
    f1_score: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    false_positive_rate: Mapped[float | None] = mapped_column(Float)
    false_negative_rate: Mapped[float | None] = mapped_column(Float)
    manual_review_rate: Mapped[float | None] = mapped_column(Float)
    dispute_rate: Mapped[float | None] = mapped_column(Float)
    merge_error_rate: Mapped[float | None] = mapped_column(Float)
    candidate_reduction_pct: Mapped[float | None] = mapped_column(Float)
    avg_candidates: Mapped[float | None] = mapped_column(Float)
    ground_truth_available: Mapped[bool] = mapped_column(Boolean, default=False)
    tp: Mapped[int | None] = mapped_column(Integer)
    fp: Mapped[int | None] = mapped_column(Integer)
    fn: Mapped[int | None] = mapped_column(Integer)
    tn: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    data_quality_json: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# H. human_review – decisions taken by a human reviewer
# ---------------------------------------------------------------------------
class HumanReview(Base):
    __tablename__ = "human_review"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(20), index=True)
    match_id: Mapped[int | None] = mapped_column(Integer, index=True)
    incoming_id: Mapped[str] = mapped_column(String(20), index=True)
    predicted_entity_id: Mapped[str | None] = mapped_column(String(20))
    predicted_decision: Mapped[str | None] = mapped_column(String(20))
    actual_entity_id: Mapped[str | None] = mapped_column(String(20))
    review_decision: Mapped[str] = mapped_column(String(30))   # CONFIRM_MATCH / REJECT_MATCH / MARK_NO_MATCH / SELECT_DIFFERENT_ENTITY
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(80))
    is_dispute: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# I. audit_logs – who did what, when
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    actor: Mapped[str | None] = mapped_column(String(80), default="system")
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    record_ref: Mapped[str | None] = mapped_column(String(80))
    algorithm_version: Mapped[str | None] = mapped_column(String(20))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Support: ground_truth – labelled "correct answers" for incoming records
# ---------------------------------------------------------------------------
class GroundTruth(Base):
    __tablename__ = "ground_truth"

    gt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incoming_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    true_entity_id: Mapped[str | None] = mapped_column(String(20))
    true_decision: Mapped[str] = mapped_column(String(20))      # MATCH / NO_MATCH
    source: Mapped[str | None] = mapped_column(String(30))      # generator / upload
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# Support: monitoring_thresholds – Green / Amber / Red boundaries per metric
# ---------------------------------------------------------------------------
class MonitoringThreshold(Base):
    __tablename__ = "monitoring_thresholds"

    metric: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    direction: Mapped[str] = mapped_column(String(20))          # higher_is_better / lower_is_better
    green: Mapped[float] = mapped_column(Float)
    amber: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


Index("ix_results_run_incoming", MatchResult.run_id, MatchResult.incoming_id)
Index("ix_candidates_run_incoming", MatchCandidate.run_id, MatchCandidate.incoming_id)
