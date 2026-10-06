"""STEP 7 – Weighted overall score.

    Overall Score = Σ (field score × effective weight) / Σ effective weights

Two important rules:

1. MISSING FIELDS ARE NOT ZERO.  If DOB is missing in either record, the DOB
   weight is removed and the remaining weights are re-normalized so they still
   sum to 100%.  Otherwise a record with a blank DOB would be punished for
   having less data rather than for being different.

2. RARE-VALUE WEIGHTING (optional).  Agreement on a value shared by only one
   master record (a phone number) is more informative than agreement on a
   value shared by thousands.  When enabled, each field weight is multiplied
   by a factor derived from the frequency of the master value.  The factor is
   capped (default 0.7 – 1.5) so it can never override the configured weights.
"""
from __future__ import annotations

import math

from utils.helpers import MATCH_FIELDS, load_config


def information_factor(frequency: int, total: int, min_factor: float | None = None,
                       max_factor: float | None = None, slope: float | None = None) -> float:
    """Frequency → multiplicative weight factor (capped)."""
    cfg = load_config().get("rare_value", {})
    min_factor = cfg.get("min_factor", 0.7) if min_factor is None else min_factor
    max_factor = cfg.get("max_factor", 1.5) if max_factor is None else max_factor
    slope = cfg.get("slope", 0.2) if slope is None else slope
    if total <= 0 or frequency <= 0:
        return 1.0
    idf = math.log10(total / frequency)          # 0 for "every record has it", large for unique values
    factor = 0.7 + slope * idf
    return round(max(min_factor, min(max_factor, factor)), 3)


def effective_weights(weights: dict[str, float], available: list[str],
                      factors: dict[str, float] | None = None) -> dict[str, float]:
    """Re-normalize weights over the available fields (and apply factors)."""
    raw = {f: weights.get(f, 0.0) * (factors or {}).get(f, 1.0) for f in available if weights.get(f, 0.0) > 0}
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {f: round(w / total * 100, 4) for f, w in raw.items()}


def overall_score(field_scores: dict[str, float | None], weights: dict[str, float],
                  factors: dict[str, float] | None = None) -> dict:
    """Compute the weighted average over available fields.

    Returns a dict with everything needed to display the full calculation.
    """
    available = [f for f in MATCH_FIELDS if field_scores.get(f) is not None]
    missing = [f for f in MATCH_FIELDS if field_scores.get(f) is None]
    eff = effective_weights(weights, available, factors)
    contributions = {f: round(field_scores[f] * eff[f] / 100, 3) for f in eff}
    score = round(sum(contributions.values()), 1) if eff else 0.0
    return {
        "overall": score,
        "available_fields": available,
        "missing_fields": missing,
        "configured_weights": {f: weights.get(f, 0.0) for f in MATCH_FIELDS},
        "information_factors": {f: (factors or {}).get(f, 1.0) for f in available},
        "effective_weights": eff,
        "contributions": contributions,
    }


def calculation_rows(breakdown: dict, field_scores: dict[str, float | None]) -> list[dict]:
    """Tabular version of the score calculation for the UI."""
    rows = []
    for f in MATCH_FIELDS:
        score = field_scores.get(f)
        rows.append({
            "Field": f.upper() if f == "dob" else f.title(),
            "Field Score": "-" if score is None else f"{score:.1f}",
            "Configured Weight %": f"{breakdown['configured_weights'].get(f, 0):.0f}",
            "Info Factor": "-" if score is None else f"{breakdown['information_factors'].get(f, 1.0):.2f}",
            "Effective Weight %": "-" if score is None else f"{breakdown['effective_weights'].get(f, 0):.1f}",
            "Contribution": "-" if score is None else f"{breakdown['contributions'].get(f, 0):.2f}",
        })
    rows.append({
        "Field": "OVERALL",
        "Field Score": "",
        "Configured Weight %": "100",
        "Info Factor": "",
        "Effective Weight %": "100.0" if breakdown["effective_weights"] else "0",
        "Contribution": f"{breakdown['overall']:.1f}",
    })
    return rows
