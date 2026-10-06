"""Plain data containers passed between the pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from utils.helpers import MATCH_FIELDS


@dataclass
class CandidateScore:
    entity_id: str
    master: dict                                 # original master values
    field_scores: dict[str, float | None]        # {field: score|None}
    field_details: dict[str, dict]               # per-field sub metrics
    breakdown: dict                              # scoring.overall_score() output
    overall: float
    blocking_methods: list[str]
    exact_rules: list[dict]
    conflicts: list[dict] = field(default_factory=list)
    rank: int = 0
    gap_to_next: float | None = None             # best only: best − second
    confidence: str | None = None
    confidence_points: int | None = None
    confidence_factors: list[dict] = field(default_factory=list)
    decision: str | None = None

    @property
    def conflict_flag(self) -> bool:
        return bool(self.conflicts)

    @property
    def critical_conflict(self) -> bool:
        return any(c.get("severity") == "CRITICAL" for c in self.conflicts)

    def strong_fields(self, level: float = 90) -> list[str]:
        return [f for f in MATCH_FIELDS if (self.field_scores.get(f) or 0) >= level]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["conflict_flag"] = self.conflict_flag
        d["critical_conflict"] = self.critical_conflict
        return d


@dataclass
class MatchOutcome:
    incoming: dict                               # original incoming values
    normalized: dict                             # normalize_record() output
    candidates: list[CandidateScore]             # ranked top-N
    pool_size: int                               # candidates after blocking
    master_size: int
    reduction_pct: float | None
    best: CandidateScore | None
    score_gap: float | None
    decision: str
    decision_rule: str
    reason: str
    confidence: str
    confidence_points: int
    confidence_factors: list[dict]
    set_conflicts: list[dict]
    algorithm_version: str
    duration_ms: float
    blocking_passes_used: list[str]

    @property
    def best_entity_id(self) -> str | None:
        return self.best.entity_id if self.best else None

    @property
    def best_score(self) -> float | None:
        return self.best.overall if self.best else None

    @property
    def conflict_flag(self) -> bool:
        return bool(self.set_conflicts) or (self.best.conflict_flag if self.best else False)

    @property
    def critical_conflict(self) -> bool:
        return any(c.get("severity") == "CRITICAL" for c in self.set_conflicts) or (
            self.best.critical_conflict if self.best else False
        )

    def all_conflicts(self) -> list[dict]:
        conflicts = list(self.best.conflicts) if self.best else []
        return conflicts + list(self.set_conflicts)

    def summary_row(self) -> dict:
        """Flat row used by result tables and Excel export."""
        return {
            "Incoming ID": self.incoming.get("incoming_id"),
            "Incoming Name": self.incoming.get("name"),
            "Best Candidate": self.best.master.get("name") if self.best else "-",
            "Entity ID": self.best_entity_id or "-",
            "Overall Score": self.best_score if self.best else None,
            "Score Gap": self.score_gap,
            "Confidence": self.confidence,
            "Conflict": "Yes" if self.conflict_flag else "No",
            "Decision": self.decision,
            "Reason": self.reason,
            "Candidates": self.pool_size,
            "Reduction %": self.reduction_pct,
        }
