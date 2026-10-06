"""STEP 4 – Exact matching rules.

Exact rules run on *normalized* values before fuzzy matching.  They do two
things:

1. Flag candidates that share highly reliable identifiers.
2. Distinguish a SINGLE matching field (an *indicator*) from a
   COMBINATION of fields (a *strong* exact match).

A single matching field is never sufficient to merge on its own – it only
contributes evidence.  Two independent identifiers agreeing (e.g. phone AND
date of birth) is treated as a strong signal and is used by the confidence
calculation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExactRule:
    rule_id: str
    label: str
    fields: tuple[str, ...]
    strong: bool          # True = reliable combination, False = single indicator


EXACT_RULES: list[ExactRule] = [
    ExactRule("exact_email", "Exact normalized email", ("email",), strong=False),
    ExactRule("exact_phone", "Exact normalized phone", ("phone",), strong=False),
    ExactRule("exact_name_dob", "Exact name + date of birth", ("name", "dob"), strong=True),
    ExactRule("exact_phone_dob", "Exact phone + date of birth", ("phone", "dob"), strong=True),
    ExactRule("exact_email_name", "Exact email + name", ("email", "name"), strong=True),
]


def _equal(inc: dict, cand: dict, field: str) -> bool:
    a, b = inc["norm"].get(field), cand["norm"].get(field)
    return bool(a) and a == b


def exact_matches(incoming: dict, candidate: dict) -> list[dict]:
    """Return every exact rule that fires for this (incoming, candidate) pair."""
    fired = []
    for rule in EXACT_RULES:
        if all(_equal(incoming, candidate, f) for f in rule.fields):
            fired.append({"rule_id": rule.rule_id, "label": rule.label, "fields": list(rule.fields), "strong": rule.strong})
    return fired


def has_strong_exact(fired_rules: list[dict]) -> bool:
    return any(r["strong"] for r in fired_rules)


def exact_summary(fired_rules: list[dict]) -> str:
    if not fired_rules:
        return "No exact rule fired."
    strong = [r["label"] for r in fired_rules if r["strong"]]
    weak = [r["label"] for r in fired_rules if not r["strong"]]
    parts = []
    if strong:
        parts.append("Strong exact match: " + ", ".join(strong))
    if weak:
        parts.append("Exact indicator: " + ", ".join(weak))
    return ". ".join(parts) + "."
