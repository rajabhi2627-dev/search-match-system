"""STEP 11/12 – Confidence score and final decision.

DECISION RULES (thresholds come from the algorithm version)
-----------------------------------------------------------
    IF   no candidate                                     → NO_MATCH
    IF   score >= match AND gap >= ambiguity AND no critical conflict → MATCH
    IF   score >= match BUT (critical conflict OR gap < ambiguity)    → MANUAL_REVIEW
    IF   manual_review <= score < match                   → MANUAL_REVIEW
    IF   score < manual_review                            → NO_MATCH

CONFIDENCE (independent from the raw score; a point system)
-----------------------------------------------------------
    similarity level            0 / 10 / 20 / 30 points
    strongly matching fields    +8 each (max 32)
    critical identifier exact   +15 (phone or email == 100, or strong exact rule)
    score gap                   0 / 8 / 15 points
    data completeness           up to 8 points
    conflicts                   −30 critical, −10 warning
    → HIGH ≥ 70, MEDIUM ≥ 45, otherwise LOW
"""
from __future__ import annotations

from dataclasses import dataclass

from matching.algorithm_config import AlgorithmConfig
from utils.helpers import MATCH_FIELDS, load_config

MATCH, MANUAL_REVIEW, NO_MATCH = "MATCH", "MANUAL_REVIEW", "NO_MATCH"


@dataclass
class Decision:
    decision: str
    rule: str        # short identifier of the rule that fired
    reason: str      # human-readable explanation


def decide(best_score: float | None, score_gap: float | None, critical_conflict: bool,
           cfg: AlgorithmConfig, conflict_text: str = "") -> Decision:
    """Apply the decision rules. Pure function – no database, no randomness."""
    m, r, g = cfg.match_threshold, cfg.manual_review_threshold, cfg.ambiguity_gap_threshold

    if best_score is None:
        return Decision(NO_MATCH, "no_candidate",
                        "No candidate was produced by blocking, so there is nothing to compare against.")

    gap = score_gap if score_gap is not None else best_score

    if best_score >= m:
        if critical_conflict:
            return Decision(MANUAL_REVIEW, "high_score_conflict",
                            f"Score {best_score:.1f} ≥ match threshold {m:.0f}, but a critical field conflict exists"
                            f"{(' – ' + conflict_text) if conflict_text else ''}. Sent to manual review.")
        if gap < g:
            return Decision(MANUAL_REVIEW, "high_score_ambiguous",
                            f"Score {best_score:.1f} ≥ match threshold {m:.0f}, but the gap to the second-best "
                            f"candidate ({gap:.1f}) is below the ambiguity threshold {g:.0f}. Two candidates are too close.")
        return Decision(MATCH, "match",
                        f"Score {best_score:.1f} ≥ match threshold {m:.0f}, no critical conflict and the score gap "
                        f"({gap:.1f}) ≥ {g:.0f}.")
    if best_score >= r:
        return Decision(MANUAL_REVIEW, "mid_score",
                        f"Score {best_score:.1f} is between the manual-review threshold {r:.0f} and the match "
                        f"threshold {m:.0f}. A human should decide.")
    return Decision(NO_MATCH, "low_score",
                    f"Best candidate score {best_score:.1f} is below the manual-review threshold {r:.0f}. "
                    f"No candidate is acceptable.")


# ------------------------------------------------------------ confidence
def confidence_score(best_score: float | None, field_scores: dict[str, float | None],
                     score_gap: float | None, conflicts: list[dict],
                     strong_exact: bool = False) -> tuple[str, int, list[dict]]:
    """Return (level, points, factors). Deterministic point system."""
    cfg = load_config().get("confidence", {})
    high_min = int(cfg.get("high_min_points", 70))
    med_min = int(cfg.get("medium_min_points", 45))
    factors: list[dict] = []

    if best_score is None:
        return "LOW", 0, [{"factor": "No candidate", "points": 0, "detail": "Nothing to assess"}]

    # 1. Similarity level
    if best_score >= 90:
        pts, lvl = 30, "≥ 90"
    elif best_score >= 80:
        pts, lvl = 20, "80–90"
    elif best_score >= 65:
        pts, lvl = 10, "65–80"
    else:
        pts, lvl = 0, "< 65"
    factors.append({"factor": "Overall similarity", "points": pts, "detail": f"Score {best_score:.1f} ({lvl})"})

    # 2. Strongly matching fields
    strong = [f for f in MATCH_FIELDS if (field_scores.get(f) or 0) >= 90]
    pts = min(32, 8 * len(strong))
    factors.append({"factor": "Strongly matching fields", "points": pts,
                    "detail": f"{len(strong)} field(s) ≥ 90: {', '.join(strong) if strong else 'none'}"})

    # 3. Critical identifier agreement
    crit = (field_scores.get("phone") == 100) or (field_scores.get("email") == 100) or strong_exact
    factors.append({"factor": "Critical identifier agreement", "points": 15 if crit else 0,
                    "detail": "Phone/email exact or strong exact rule" if crit else "No exact identifier agreement"})

    # 4. Score gap
    gap = score_gap if score_gap is not None else best_score
    pts = 15 if gap >= 10 else 8 if gap >= 5 else 0
    factors.append({"factor": "Score gap", "points": pts, "detail": f"Gap {gap:.1f}"})

    # 5. Data completeness
    available = [f for f in MATCH_FIELDS if field_scores.get(f) is not None]
    pts = round(8 * len(available) / len(MATCH_FIELDS))
    factors.append({"factor": "Data completeness", "points": pts, "detail": f"{len(available)}/{len(MATCH_FIELDS)} fields comparable"})

    # 6. Conflicts
    n_crit = sum(1 for c in conflicts if c.get("severity") == "CRITICAL")
    n_warn = sum(1 for c in conflicts if c.get("severity") == "WARNING")
    pts = -30 * n_crit - 10 * n_warn
    factors.append({"factor": "Conflicts", "points": pts,
                    "detail": f"{n_crit} critical, {n_warn} warning" if (n_crit or n_warn) else "None"})

    total = max(0, min(100, sum(f["points"] for f in factors)))
    level = "HIGH" if total >= high_min else "MEDIUM" if total >= med_min else "LOW"
    return level, total, factors


# ----------------------------------------------------------- explanation
def build_explanation(decision: Decision, best, field_scores: dict[str, float | None],
                      score_gap: float | None, conflicts: list[dict], pool_size: int, n_ranked: int) -> str:
    """Plain-language narrative for the match explanation panel."""
    if best is None:
        return ("No master record shared a blocking key (phone, email, postal code + surname, city + surname, "
                "phonetic surname or first name + city) with the incoming record. Decision: NO_MATCH.")

    strong = [f for f in MATCH_FIELDS if (field_scores.get(f) or 0) >= 90]
    medium = [f for f in MATCH_FIELDS if field_scores.get(f) is not None and 70 <= field_scores[f] < 90]
    weak = [f for f in MATCH_FIELDS if field_scores.get(f) is not None and field_scores[f] < 50]
    missing = [f for f in MATCH_FIELDS if field_scores.get(f) is None]

    def lab(fs: list[str]) -> str:
        return ", ".join("DOB" if f == "dob" else f for f in fs)

    parts = []
    if strong:
        parts.append(f"Strong agreement across {lab(strong)}.")
    if medium:
        parts.append(f"{lab(medium).capitalize()} also show{'s' if len(medium) == 1 else ''} high similarity.")
    if weak:
        parts.append(f"{lab(weak).capitalize()} differ{'s' if len(weak) == 1 else ''} substantially.")
    if missing:
        parts.append(f"{lab(missing).capitalize()} could not be compared (missing in one record) – weights were re-normalized over the available fields.")
    gap = score_gap if score_gap is not None else best.overall
    if n_ranked > 1:
        if gap >= 10:
            parts.append("The best candidate is clearly separated from the second-best candidate.")
        elif gap >= 5:
            parts.append("The best candidate is sufficiently separated from the second-best candidate.")
        else:
            parts.append(f"The second-best candidate is only {gap:.1f} points behind – the ranking is ambiguous.")
    else:
        parts.append(f"It was the only candidate among {pool_size} record(s) produced by blocking.")
    crit = [c["message"] for c in conflicts if c.get("severity") == "CRITICAL"]
    warn = [c["message"] for c in conflicts if c.get("severity") == "WARNING"]
    if crit:
        parts.append("Critical conflict: " + " ".join(crit))
    if warn:
        parts.append("Warning: " + " ".join(warn))
    parts.append(f"Decision rule: {decision.reason}")
    return " ".join(parts)
