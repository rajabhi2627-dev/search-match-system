"""FEBRL benchmark datasets → master / incoming / ground truth.

FEBRL (Freely Extensible Biomedical Record Linkage, Australian National
University – Christen & Churches) ships four synthetic benchmark datasets that
are the de-facto standard for testing record-linkage algorithms.  Every record
ID encodes the truth:

    rec-1070-org     an ORIGINAL record
    rec-1070-dup-0   a corrupted DUPLICATE of rec-1070-org (typos, swapped
                     fields, missing values, changed suburb, ...)

So the datasets give us a labelled benchmark for free:

    originals  → MASTER database          (entity_id  F01070)
    duplicates → INCOMING records         (true_entity_id F01070, MATCH)

To obtain genuine *no-match* cases (needed for TN / FPR) a configurable share
of originals is HELD OUT of the master; their duplicates then have no true
counterpart and are labelled NO_MATCH.

Column mapping (FEBRL has no e-mail, phone or company):

    given_name + surname                  → name
    street_number + address_1 + address_2 → address
    suburb / state / postcode             → city / state / postal_code
    date_of_birth  YYYYMMDD               → YYYY-MM-DD
    soc_sec_id                            → phone  (numeric identifier slot;
                                            optional, clearly labelled in UI)
    email, company                        → empty → weights re-normalize

Datasets (CSV copies bundled in data/febrl/, from the `recordlinkage`
project's redistribution of the original FEBRL files):

    dataset1   1,000 records =   500 originals +   500 duplicates (1 per original)
    dataset2   5,000 records = 4,000 originals + 1,000 duplicates (≤ 5 per original)
    dataset3   5,000 records = 2,000 originals + 3,000 duplicates (≤ 5 per original)
    dataset4   dataset4a = 5,000 originals, dataset4b = 5,000 duplicates (1 per original)
"""
from __future__ import annotations

import io
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from utils.helpers import PROJECT_ROOT, RECORD_FIELDS, clean_value

FEBRL_DIR = PROJECT_ROOT / "data" / "febrl"

FEBRL_COLUMNS = ["rec_id", "given_name", "surname", "street_number", "address_1", "address_2",
                 "suburb", "postcode", "state", "date_of_birth", "soc_sec_id"]

FEBRL_DATASETS = {
    "dataset1": {"label": "FEBRL dataset 1 – 500 originals + 500 duplicates (1 duplicate each)",
                 "files": ["dataset1.csv"]},
    "dataset2": {"label": "FEBRL dataset 2 – 4,000 originals + 1,000 duplicates (up to 5 each)",
                 "files": ["dataset2.csv"]},
    "dataset3": {"label": "FEBRL dataset 3 – 2,000 originals + 3,000 duplicates (up to 5 each)",
                 "files": ["dataset3.csv"]},
    "dataset4": {"label": "FEBRL dataset 4 – 5,000 originals (4a) + 5,000 duplicates (4b)",
                 "files": ["dataset4a.csv", "dataset4b.csv"]},
}

SCENARIO_DUP = "F1 FEBRL duplicate of a master record"
SCENARIO_HOLDOUT = "F2 FEBRL duplicate of a held-out original (no match)"

_REC_RE = re.compile(r"^rec-(\d+)-(org|dup)(?:-(\d+))?$")


# ------------------------------------------------------------------ parsing
def parse_rec_id(rec_id: str) -> tuple[int, str, int | None]:
    """'rec-1070-dup-2' → (1070, 'dup', 2);  'rec-1070-org' → (1070, 'org', None)."""
    m = _REC_RE.match(str(rec_id).strip())
    if not m:
        raise ValueError(f"Not a FEBRL record id: {rec_id!r}")
    return int(m.group(1)), m.group(2), (int(m.group(3)) if m.group(3) is not None else None)


def entity_id_for(rec_num: int) -> str:
    return f"F{rec_num:05d}"


def read_febrl(source) -> pd.DataFrame:
    """Read a FEBRL CSV (path, bytes or file-like). Header and values are whitespace-stripped."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    df = pd.read_csv(source, dtype=str, keep_default_na=False, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in FEBRL_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Not a FEBRL file – missing columns: {', '.join(missing)}")
    for c in FEBRL_COLUMNS:
        df[c] = df[c].astype(str).str.strip()
    return df[FEBRL_COLUMNS]


def load_bundled(dataset: str) -> pd.DataFrame:
    if dataset not in FEBRL_DATASETS:
        raise ValueError(f"Unknown FEBRL dataset {dataset!r}; choose from {list(FEBRL_DATASETS)}")
    frames = [read_febrl(FEBRL_DIR / f) for f in FEBRL_DATASETS[dataset]["files"]]
    return pd.concat(frames, ignore_index=True)


def bundled_available(dataset: str) -> bool:
    return all((FEBRL_DIR / f).exists() for f in FEBRL_DATASETS[dataset]["files"])


# ------------------------------------------------------------- conversion
def _iso_dob(raw: str) -> str | None:
    raw = clean_value(raw)
    if raw is None:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return raw            # keep corrupted value – the normalizer will treat it as unparseable


def to_record(row: pd.Series | dict, id_as_phone: bool = True) -> dict:
    """Map one FEBRL row to the system's record schema."""
    def g(k: str):
        return clean_value(row.get(k))
    name = " ".join(p for p in (g("given_name"), g("surname")) if p)
    address = " ".join(p for p in (g("street_number"), g("address_1"), g("address_2")) if p)
    rec = {
        "name": name or None,
        "email": None,
        "phone": g("soc_sec_id") if id_as_phone else None,
        "address": address or None,
        "date_of_birth": _iso_dob(g("date_of_birth")),
        "company": None,
        "city": g("suburb"),
        "state": (g("state") or "").upper() or None,
        "postal_code": g("postcode"),
    }
    return {f: rec.get(f) for f in RECORD_FIELDS}


# ------------------------------------------------------------------ split
@dataclass
class FebrlSplit:
    dataset: str
    master_records: list[dict]
    incoming_records: list[dict]
    ground_truth: list[dict]          # {"row": i, "true_entity_id": ..., "true_decision": ...}
    stats: dict = field(default_factory=dict)


def split_febrl(df: pd.DataFrame, dataset: str = "custom", holdout_pct: float = 10.0, seed: int = 42,
                id_as_phone: bool = True) -> FebrlSplit:
    """Originals → master, duplicates → incoming (+ labels). `holdout_pct` of originals are removed
    from the master so their duplicates become true NO_MATCH cases."""
    parsed = [parse_rec_id(r) for r in df["rec_id"]]
    originals = [(i, num) for i, (num, kind, _) in enumerate(parsed) if kind == "org"]
    duplicates = [(i, num, idx) for i, (num, kind, idx) in enumerate(parsed) if kind == "dup"]

    org_nums = sorted({num for _, num in originals})
    rng = random.Random(seed)
    n_hold = int(round(len(org_nums) * max(0.0, min(100.0, holdout_pct)) / 100.0))
    held_out = set(rng.sample(org_nums, n_hold)) if n_hold else set()

    master, seen = [], set()
    for i, num in sorted(originals, key=lambda t: t[1]):
        if num in held_out or num in seen:
            continue
        seen.add(num)
        rec = to_record(df.iloc[i], id_as_phone)
        rec["entity_id"] = entity_id_for(num)
        rec["source"] = f"febrl:{dataset}:{df.iloc[i]['rec_id']}"
        master.append(rec)

    incoming, truth = [], []
    for row_no, (i, num, idx) in enumerate(sorted(duplicates, key=lambda t: (t[1], t[2] or 0))):
        rec = to_record(df.iloc[i], id_as_phone)
        rec["source_rec_id"] = df.iloc[i]["rec_id"]
        if num in seen:
            rec["scenario"] = SCENARIO_DUP
            truth.append({"row": row_no, "true_entity_id": entity_id_for(num), "true_decision": "MATCH"})
        else:
            rec["scenario"] = SCENARIO_HOLDOUT
            truth.append({"row": row_no, "true_entity_id": None, "true_decision": "NO_MATCH"})
        incoming.append(rec)

    stats = {
        "rows": len(df), "originals": len(org_nums), "duplicates": len(duplicates),
        "held_out_originals": len(held_out), "master": len(master), "incoming": len(incoming),
        "true_match": sum(1 for t in truth if t["true_decision"] == "MATCH"),
        "true_no_match": sum(1 for t in truth if t["true_decision"] == "NO_MATCH"),
        "id_as_phone": id_as_phone,
    }
    return FebrlSplit(dataset=dataset, master_records=master, incoming_records=incoming, ground_truth=truth, stats=stats)


def preview_frame(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Side-by-side original vs duplicate pairs for the UI."""
    by_num: dict[int, dict] = {}
    for _, row in df.iterrows():
        num, kind, _ = parse_rec_id(row["rec_id"])
        by_num.setdefault(num, {}).setdefault(kind, row)
    rows = []
    for num in sorted(by_num):
        pair = by_num[num]
        if "org" in pair and "dup" in pair:
            o, d = pair["org"], pair["dup"]
            rows.append({"Entity": entity_id_for(num),
                         "Original name": f"{o['given_name']} {o['surname']}".strip(),
                         "Duplicate name": f"{d['given_name']} {d['surname']}".strip(),
                         "Original address": f"{o['street_number']} {o['address_1']} {o['address_2']}, {o['suburb']} {o['postcode']}".strip(),
                         "Duplicate address": f"{d['street_number']} {d['address_1']} {d['address_2']}, {d['suburb']} {d['postcode']}".strip(),
                         "Original DOB": o["date_of_birth"], "Duplicate DOB": d["date_of_birth"],
                         "Original ID": o["soc_sec_id"], "Duplicate ID": d["soc_sec_id"]})
        if len(rows) >= n:
            break
    return pd.DataFrame(rows)
