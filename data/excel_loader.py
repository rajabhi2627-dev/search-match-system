"""Excel / CSV loader for incoming batches and ground-truth files.

Column names are matched case-insensitively and common aliases are accepted
(e.g. "Full Name", "Mobile", "E-mail", "DOB", "Pincode").
"""
from __future__ import annotations

import io
import re
from typing import IO

import pandas as pd

from utils.helpers import RECORD_FIELDS

COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["name", "full name", "fullname", "customer name", "customer", "person", "applicant name"],
    "email": ["email", "e-mail", "email address", "mail", "email id", "emailid"],
    "phone": ["phone", "mobile", "phone number", "mobile number", "contact", "contact number", "telephone", "phone no", "mobile no"],
    "address": ["address", "street address", "addr", "address line", "address1", "residential address"],
    "date_of_birth": ["date_of_birth", "dob", "date of birth", "birth date", "birthdate", "birthday"],
    "company": ["company", "employer", "organisation", "organization", "company name", "firm"],
    "city": ["city", "town", "district"],
    "state": ["state", "province", "region"],
    "postal_code": ["postal_code", "postal code", "pincode", "pin code", "pin", "zip", "zip code", "postcode"],
    "incoming_id": ["incoming_id", "incoming id", "record id", "id"],
    "true_entity_id": ["true_entity_id", "true entity id", "entity_id", "entity id", "correct entity", "expected entity"],
    "true_decision": ["true_decision", "true decision", "expected decision", "decision", "label"],
}


def _canon(col: str) -> str:
    return re.sub(r"[\s_\-\.]+", " ", str(col).strip().lower())


def standardize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rename recognised columns to the standard names. Returns (df, mapping)."""
    lookup = {}
    for std, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup[_canon(alias)] = std
    mapping = {}
    for col in df.columns:
        std = lookup.get(_canon(col))
        if std and std not in mapping.values():
            mapping[col] = std
    out = df.rename(columns=mapping)
    out.columns = [str(c) for c in out.columns]
    return out, mapping


def read_table(file: IO[bytes] | str, filename: str | None = None) -> pd.DataFrame | None:
    """Read .xlsx or .csv into a DataFrame (all columns as strings). None on failure."""
    name = (filename or getattr(file, "name", "") or str(file)).lower()
    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            df = pd.read_excel(file, dtype=str)
        elif name.endswith(".csv"):
            raw = file.read() if hasattr(file, "read") else open(file, "rb").read()
            if isinstance(raw, bytes):
                for enc in ("utf-8-sig", "utf-8", "latin-1"):
                    try:
                        text = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    return None
            else:
                text = raw
            df = pd.read_csv(io.StringIO(text), dtype=str)
        else:
            return None
    except Exception:
        return None
    df = df.dropna(how="all")
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    return df


def load_incoming_file(file: IO[bytes] | str, filename: str | None = None) -> tuple[pd.DataFrame | None, dict[str, str]]:
    """Read a file and standardize its columns for the matching pipeline."""
    df = read_table(file, filename)
    if df is None:
        return None, {}
    df, mapping = standardize_columns(df)
    for col in RECORD_FIELDS:
        if col not in df.columns:
            df[col] = None
    df = df.where(pd.notna(df), None)
    return df, mapping


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → list of plain dicts limited to the record fields (+ optional incoming_id)."""
    cols = [c for c in RECORD_FIELDS + ["incoming_id"] if c in df.columns]
    records = []
    for row in df[cols].itertuples(index=False):
        rec = {c: (None if pd.isna(v) else v) for c, v in zip(cols, row)}
        records.append(rec)
    return records


def incoming_template() -> pd.DataFrame:
    """Template with the expected columns and two example rows."""
    return pd.DataFrame([
        {"name": "RAHUL SHARMA", "email": "rahul.sharma@gmail.com", "phone": "+91 9876543210",
         "address": "12 Mahatma Gandhi Road Patna", "date_of_birth": "1988-05-14", "company": "TCS",
         "city": "Patna", "state": "Bihar", "postal_code": "800001"},
        {"name": "Priya Singh", "email": "", "phone": "9123456780", "address": "45 Boring Rd, Patna",
         "date_of_birth": "", "company": "", "city": "Patna", "state": "Bihar", "postal_code": "800013"},
    ])


def ground_truth_template() -> pd.DataFrame:
    return pd.DataFrame([
        {"incoming_id": "I000001", "true_entity_id": "C01023", "true_decision": "MATCH"},
        {"incoming_id": "I000002", "true_entity_id": "", "true_decision": "NO_MATCH"},
    ])
