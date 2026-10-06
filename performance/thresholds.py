"""Green / Amber / Red monitoring threshold evaluation.

These are PROTOTYPE monitoring thresholds chosen for demonstration.  They are
not regulatory or industry-mandated values and can be changed by the user on
the Thresholds page.
"""
from __future__ import annotations


def rag_status(value: float | None, direction: str, green: float, amber: float) -> str | None:
    """Return GREEN / AMBER / RED (or None when the metric is unavailable).

    higher_is_better:  value >= green → GREEN, value >= amber → AMBER, else RED
    lower_is_better:   value <= green → GREEN, value <= amber → AMBER, else RED
    """
    if value is None:
        return None
    if direction == "higher_is_better":
        if value >= green:
            return "GREEN"
        return "AMBER" if value >= amber else "RED"
    if value <= green:
        return "GREEN"
    return "AMBER" if value <= amber else "RED"


def threshold_text(direction: str, green: float, amber: float) -> dict[str, str]:
    if direction == "higher_is_better":
        return {"GREEN": f"≥ {green:g}%", "AMBER": f"{amber:g}–{green:g}%", "RED": f"< {amber:g}%"}
    return {"GREEN": f"≤ {green:g}%", "AMBER": f"{green:g}–{amber:g}%", "RED": f"> {amber:g}%"}


def validate_threshold(direction: str, green: float, amber: float) -> str | None:
    if direction == "higher_is_better" and amber > green:
        return "For 'higher is better' metrics the amber boundary must be ≤ the green boundary."
    if direction == "lower_is_better" and amber < green:
        return "For 'lower is better' metrics the amber boundary must be ≥ the green boundary."
    return None
