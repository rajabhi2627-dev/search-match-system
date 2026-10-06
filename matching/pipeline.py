"""The MatchEngine – runs the full Search & Match pipeline for one record.

    normalize → block → exact rules → fuzzy field scores → weighted score
    → conflicts → rank → score gap → confidence → decision → explanation

The engine is deterministic: the same (config, master index, record) always
produces the same output.  It does not touch the database; persistence is
handled by database/repository.py so the engine can be unit-tested in
isolation and reused for regression / stability tests.
"""
from __future__ import annotations

import time

from matching.algorithm_config import AlgorithmConfig
from matching.blocking import BlockingIndex, reduction_pct
from matching.conflict_detection import conflict_summary, detect_conflicts, detect_set_conflicts, has_critical
from matching.decision_engine import build_explanation, confidence_score, decide
from matching.exact_match import exact_matches, has_strong_exact
from matching.fuzzy_match import compute_field_scores, scores_only
from matching.preprocessing import normalize_record
from matching.ranking import rank_candidates, score_gap
from matching.scoring import information_factor, overall_score
from matching.types import CandidateScore, MatchOutcome
from utils.helpers import MATCH_FIELDS


class MatchEngine:
    def __init__(self, config: AlgorithmConfig, index: BlockingIndex):
        self.config = config
        self.index = index

    # ---------------------------------------------------------------- utils
    def _info_factors(self, candidate_norm: dict) -> dict[str, float] | None:
        """Rare-value factors for the candidate's values (optional feature)."""
        if not self.config.rare_value_weighting:
            return None
        total = self.index.size
        factors = {}
        for f in MATCH_FIELDS:
            value = candidate_norm["norm"].get(f)
            if value:
                factors[f] = information_factor(self.index.frequency(f, value), total)
        return factors

    def _score_candidate(self, incoming_norm: dict, entity_id: str, passes: list[str]) -> CandidateScore:
        cand_norm = self.index.get(entity_id)
        details = compute_field_scores(incoming_norm, cand_norm)
        scores = scores_only(details)
        breakdown = overall_score(scores, self.config.weights, self._info_factors(cand_norm))
        conflicts = [c.to_dict() for c in detect_conflicts(scores)]
        return CandidateScore(
            entity_id=entity_id,
            master=cand_norm["original"],
            field_scores=scores,
            field_details=details,
            breakdown=breakdown,
            overall=breakdown["overall"],
            blocking_methods=list(passes),
            exact_rules=exact_matches(incoming_norm, cand_norm),
            conflicts=conflicts,
        )

    # ------------------------------------------------------------- matching
    def match_record(self, record: dict) -> MatchOutcome:
        start = time.perf_counter()
        incoming_norm = normalize_record(record)

        # STEP 2/3 – blocking
        pool = self.index.candidates(incoming_norm, self.config.blocking_passes, self.config.full_scan_if_master_below)

        # STEP 4–8 – score every candidate in the pool
        scored = [self._score_candidate(incoming_norm, eid, passes) for eid, passes in pool.items()]

        # STEP 9/10 – ranking and gap
        ranked = rank_candidates(scored, self.config.top_n)
        gap = score_gap(ranked)
        best = ranked[0] if ranked else None
        set_conflicts = [c.to_dict() for c in detect_set_conflicts(ranked)]

        # STEP 11 – confidence for every ranked candidate (best uses the real gap)
        for cand in ranked:
            cand_gap = gap if cand.rank == 1 else round(cand.overall - ranked[0].overall, 1)
            cand_conflicts = cand.conflicts + (set_conflicts if cand.rank == 1 else [])
            level, pts, factors = confidence_score(cand.overall, cand.field_scores, cand_gap,
                                                   cand_conflicts, has_strong_exact(cand.exact_rules))
            cand.confidence, cand.confidence_points, cand.confidence_factors = level, pts, factors
            # a per-candidate decision shows what WOULD happen if this candidate were the best
            cand.decision = decide(cand.overall, cand_gap if cand.rank == 1 else 0.0,
                                   has_critical(cand_conflicts), self.config).decision

        # STEP 12 – final decision on the best candidate
        all_conflicts = (best.conflicts if best else []) + set_conflicts
        critical = has_critical(all_conflicts)
        decision = decide(best.overall if best else None, gap, critical, self.config,
                          conflict_summary([c for c in all_conflicts if c["severity"] == "CRITICAL"]) if critical else "")
        if best:
            confidence, points, factors = best.confidence, best.confidence_points, best.confidence_factors
        else:
            confidence, points, factors = confidence_score(None, {}, None, [])
        reason = build_explanation(decision, best, best.field_scores if best else {}, gap, all_conflicts, len(pool), len(ranked))

        return MatchOutcome(
            incoming=incoming_norm["original"] | {"incoming_id": record.get("incoming_id")},
            normalized=incoming_norm,
            candidates=ranked,
            pool_size=len(pool),
            master_size=self.index.size,
            reduction_pct=reduction_pct(self.index.size, len(pool)),
            best=best,
            score_gap=gap,
            decision=decision.decision,
            decision_rule=decision.rule,
            reason=reason,
            confidence=confidence,
            confidence_points=points,
            confidence_factors=factors,
            set_conflicts=set_conflicts,
            algorithm_version=self.config.version_name,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            blocking_passes_used=list(self.config.blocking_passes),
        )

    def match_many(self, records: list[dict]) -> list[MatchOutcome]:
        return [self.match_record(r) for r in records]


def build_engine(config: AlgorithmConfig, master_records: list[dict]) -> MatchEngine:
    """Convenience: build the index and the engine in one call."""
    return MatchEngine(config, BlockingIndex(master_records))
