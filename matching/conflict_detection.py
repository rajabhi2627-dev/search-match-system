"""STEP 8 – Conflict detection.

The overall score can hide a serious disagreement: name 96, phone 100,
address 90 but email 20 still averages above 85.  Conflict detection looks
at *pairs* of fields and raises a flag when strong agreement in one field
coexists with clear disagreement in another.

Severity
--------
* CRITICAL – identity-defining disagreement; the decision engine will never
  return MATCH automatically when a critical conflict exists.
* WARNING  – worth showing to a reviewer, but does not block MATCH by itself.

A second, candidate-SET level check detects the case where different strong
identifiers point to *different* master entities (e.g. the phone matches
entity A exactly but the email matches entity B exactly).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from utils.helpers import load_config


@dataclass
class Conflict:
    rule_id: str
    severity: str           # CRITICAL / WARNING
    fields: list[str]
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _levels() -> tuple[float, float, float]:
    cfg = load_config().get("conflict", {})
    return float(cfg.get("strong", 90)), float(cfg.get("weak", 30)), float(cfg.get("name_mismatch", 50))


def detect_conflicts(scores: dict[str, float | None]) -> list[Conflict]:
    """Field-pair conflict rules for ONE candidate. `scores` = {field: score|None}."""
    strong, weak, name_mismatch = _levels()
    s = scores
    conflicts: list[Conflict] = []

    def present(f: str) -> bool:
        return s.get(f) is not None

    # 1. Very strong name but completely different phone
    if present("name") and present("phone") and s["name"] >= strong and s["phone"] <= weak:
        conflicts.append(Conflict("name_vs_phone", "CRITICAL", ["name", "phone"],
                                  "Potential identity conflict: name agrees strongly but the phone number is completely different."))

    # 2. Very strong phone but completely different email
    if present("phone") and present("email") and s["phone"] >= 100 and s["email"] <= weak:
        conflicts.append(Conflict("phone_vs_email", "CRITICAL", ["phone", "email"],
                                  "Potential identity conflict: email differs significantly from other fields (phone is an exact match)."))

    # 3. Exact email but completely different phone
    if present("email") and present("phone") and s["email"] >= 100 and s["phone"] <= weak:
        conflicts.append(Conflict("email_vs_phone", "CRITICAL", ["email", "phone"],
                                  "Potential identity conflict: email is an exact match but the phone number is completely different."))

    # 4. Exact DOB but conflicting identity (name) field
    if present("dob") and present("name") and s["dob"] >= 100 and s["name"] <= name_mismatch:
        conflicts.append(Conflict("dob_vs_name", "CRITICAL", ["dob", "name"],
                                  "Same date of birth but the names differ substantially – possibly a different person."))

    # 5. Strong name but DOB differs (warning – DOB entry errors are common)
    if present("name") and present("dob") and s["name"] >= strong and s["dob"] == 0:
        conflicts.append(Conflict("name_vs_dob", "WARNING", ["name", "dob"],
                                  "Name agrees strongly but the dates of birth differ."))

    # 6. Strong name, email differs, no phone available to arbitrate
    if present("name") and present("email") and not present("phone") and s["name"] >= strong and s["email"] <= weak:
        conflicts.append(Conflict("name_vs_email_no_phone", "WARNING", ["name", "email"],
                                  "Name agrees strongly but the email differs and no phone is available to confirm identity."))

    # 7. Same address but different name (household member?)
    if present("address") and present("name") and s["address"] >= strong and s["name"] <= name_mismatch:
        conflicts.append(Conflict("address_vs_name", "WARNING", ["address", "name"],
                                  "Same address but different name – could be a family member or co-resident."))

    return conflicts


def has_critical(conflicts: list[Conflict] | list[dict]) -> bool:
    return any((c.severity if isinstance(c, Conflict) else c.get("severity")) == "CRITICAL" for c in conflicts)


def detect_set_conflicts(ranked: list) -> list[Conflict]:
    """Candidate-set rule: strong identifiers pointing at different entities.

    `ranked` is a list of CandidateScore objects (see matching/types.py).
    Looks only at exact (100) phone / email agreement.
    """
    if len(ranked) < 2:
        return []
    exact_phone = {c.entity_id for c in ranked if c.field_scores.get("phone") == 100}
    exact_email = {c.entity_id for c in ranked if c.field_scores.get("email") == 100}
    if exact_phone and exact_email and exact_phone.isdisjoint(exact_email):
        return [Conflict(
            "split_identifiers", "CRITICAL", ["phone", "email"],
            f"Multiple fields point to different candidates: phone matches {', '.join(sorted(exact_phone))} "
            f"but email matches {', '.join(sorted(exact_email))}.",
        )]
    return []


def conflict_summary(conflicts: list[Conflict] | list[dict]) -> str:
    if not conflicts:
        return "None"
    parts = []
    for c in conflicts:
        d = c.to_dict() if isinstance(c, Conflict) else c
        parts.append(f"[{d['severity']}] {d['message']}")
    return " ".join(parts)
