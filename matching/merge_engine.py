"""STEP 13 – Controlled merge.

Nothing is merged automatically.  The UI shows the master record next to the
incoming record, highlights differences, lets the user choose per field which
value survives, and only then writes the merge.  Every action (CONFIRMED,
REJECTED, REVERSED) is stored in merge_history together with the old and new
values so a merge can be audited or undone.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from matching.preprocessing import normalize_record
from utils.helpers import FIELD_LABELS, RECORD_FIELDS


@dataclass
class FieldDiff:
    field: str
    label: str
    master_value: str | None
    incoming_value: str | None
    differs: bool              # raw strings differ
    normalized_equal: bool     # but normalized values are identical (format-only difference)
    status: str                # SAME / FORMAT_ONLY / DIFFERENT / INCOMING_FILLS_BLANK / MASTER_ONLY

    def to_dict(self) -> dict:
        return asdict(self)


def compare_records(master: dict, incoming: dict) -> list[FieldDiff]:
    """Field-by-field comparison used by the Merge Review page."""
    m_norm = normalize_record(master)["norm"]
    i_norm = normalize_record(incoming)["norm"]
    diffs: list[FieldDiff] = []
    for f in RECORD_FIELDS:
        mv, iv = master.get(f), incoming.get(f)
        mv = None if mv in ("", None) else str(mv)
        iv = None if iv in ("", None) else str(iv)
        norm_key = "dob" if f == "date_of_birth" else f
        n_equal = (m_norm.get(norm_key) is not None) and (m_norm.get(norm_key) == i_norm.get(norm_key))
        if mv == iv:
            status = "SAME"
        elif mv is None and iv is not None:
            status = "INCOMING_FILLS_BLANK"
        elif iv is None and mv is not None:
            status = "MASTER_ONLY"
        elif n_equal:
            status = "FORMAT_ONLY"
        else:
            status = "DIFFERENT"
        diffs.append(FieldDiff(f, FIELD_LABELS[f], mv, iv, mv != iv, n_equal, status))
    return diffs


def default_choices(diffs: list[FieldDiff]) -> dict[str, str]:
    """Default survivorship rule: keep master, but fill blanks from incoming."""
    return {d.field: ("incoming" if d.status == "INCOMING_FILLS_BLANK" else "master") for d in diffs}


def build_merged_record(master: dict, incoming: dict, choices: dict[str, str]) -> dict:
    """Apply the per-field choices and return the new master values."""
    merged = {}
    for f in RECORD_FIELDS:
        merged[f] = incoming.get(f) if choices.get(f) == "incoming" else master.get(f)
    return merged


def changed_fields(master: dict, merged: dict) -> dict[str, dict]:
    return {
        f: {"old": master.get(f), "new": merged.get(f)}
        for f in RECORD_FIELDS
        if (master.get(f) or None) != (merged.get(f) or None)
    }
