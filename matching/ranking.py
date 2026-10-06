"""STEP 9/10 – Top-N ranking and score gap.

Candidates are sorted by overall score (highest first).  Ties are broken by
entity_id so the order is always the same – determinism matters.

    Score Gap = Best candidate score − Second-best candidate score

A small gap means two master records look almost equally likely – the match
is *ambiguous* and should go to a human.  When only one candidate exists the
second-best score is treated as 0, i.e. the gap equals the best score.
"""
from __future__ import annotations

from matching.types import CandidateScore


def rank_candidates(candidates: list[CandidateScore], top_n: int = 5) -> list[CandidateScore]:
    """Return the top-N candidates with `rank` and `gap_to_next` filled in."""
    ordered = sorted(candidates, key=lambda c: (-c.overall, c.entity_id))
    top = ordered[:top_n]
    for i, cand in enumerate(top, start=1):
        cand.rank = i
        nxt = top[i].overall if i < len(top) else 0.0
        cand.gap_to_next = round(cand.overall - nxt, 1)
    return top


def score_gap(ranked: list[CandidateScore]) -> float | None:
    """Best minus second-best (second treated as 0 when absent)."""
    if not ranked:
        return None
    second = ranked[1].overall if len(ranked) > 1 else 0.0
    return round(ranked[0].overall - second, 1)
