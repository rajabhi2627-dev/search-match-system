"""Input validation and data-quality profiling for incoming data.

Used by the Batch Upload page BEFORE matching so that poor matching results
can be explained by poor input data (missing phones, invalid emails, ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from utils.helpers import RECORD_FIELDS, is_missing

REQUIRED_COLUMNS = ["name"]
IDENTIFIER_COLUMNS = ["email", "phone", "address"]   # at least one must exist
OPTIONAL_COLUMNS = ["date_of_birth", "company", "city", "state", "postal_code"]

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass
class ValidationReport:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_count: int = 0
    duplicate_rows: int = 0
    quality: dict = field(default_factory=dict)


def is_valid_email(value) -> bool:
    if is_missing(value):
        return False
    return bool(EMAIL_RE.match(str(value).strip()))


def is_valid_phone(value) -> bool:
    """Valid if it contains 10 digits after removing country code / punctuation."""
    if is_missing(value):
        return False
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return len(digits) == 10 and digits[0] in "6789"


def data_quality_profile(df: pd.DataFrame) -> dict:
    """Percentages of missing / invalid / duplicate values."""
    n = len(df)
    if n == 0:
        return {}

    def missing_pct(col: str) -> float:
        if col not in df.columns:
            return 100.0
        return round(df[col].apply(is_missing).mean() * 100, 1)

    def invalid_pct(col: str, fn) -> float:
        if col not in df.columns:
            return 0.0
        present = df[col][~df[col].apply(is_missing)]
        if present.empty:
            return 0.0
        return round((~present.apply(fn)).mean() * 100, 1)

    key_cols = [c for c in RECORD_FIELDS if c in df.columns]
    dup_pct = round(df[key_cols].astype(str).duplicated().mean() * 100, 1) if key_cols else 0.0

    return {
        "rows": n,
        "missing_name_pct": missing_pct("name"),
        "missing_email_pct": missing_pct("email"),
        "missing_phone_pct": missing_pct("phone"),
        "missing_address_pct": missing_pct("address"),
        "missing_dob_pct": missing_pct("date_of_birth"),
        "duplicate_input_pct": dup_pct,
        "invalid_email_pct": invalid_pct("email", is_valid_email),
        "invalid_phone_pct": invalid_pct("phone", is_valid_phone),
    }


def validate_incoming_df(df: pd.DataFrame | None) -> ValidationReport:
    """Validate an uploaded / generated DataFrame of incoming records."""
    report = ValidationReport(is_valid=True)
    if df is None:
        report.is_valid = False
        report.errors.append("The file could not be read. Please upload a valid .xlsx or .csv file.")
        return report
    if df.empty:
        report.is_valid = False
        report.errors.append("The file is empty – no data rows were found.")
        return report

    report.row_count = len(df)
    cols = set(df.columns)

    for col in REQUIRED_COLUMNS:
        if col not in cols:
            report.is_valid = False
            report.errors.append(f"Required column missing: '{col}'.")
    if not any(c in cols for c in IDENTIFIER_COLUMNS):
        report.is_valid = False
        report.errors.append("At least one identifier column is required: email, phone or address.")
    for col in OPTIONAL_COLUMNS:
        if col not in cols:
            report.warnings.append(f"Optional column '{col}' not found – it will be treated as missing.")

    if "name" in cols:
        blank = int(df["name"].apply(is_missing).sum())
        if blank == len(df):
            report.is_valid = False
            report.errors.append("All names are blank.")
        elif blank:
            report.warnings.append(f"{blank} row(s) have a blank name.")

    if "date_of_birth" in cols:
        from matching.preprocessing import normalize_dob
        present = df["date_of_birth"][~df["date_of_birth"].apply(is_missing)]
        bad = int(present.apply(lambda v: normalize_dob(v) is None).sum())
        if bad:
            report.warnings.append(f"{bad} date_of_birth value(s) could not be parsed as dates and will be ignored.")

    key_cols = [c for c in RECORD_FIELDS if c in cols]
    report.duplicate_rows = int(df[key_cols].astype(str).duplicated().sum()) if key_cols else 0
    if report.duplicate_rows:
        report.warnings.append(f"{report.duplicate_rows} duplicate row(s) detected (identical values). They will still be processed.")

    report.quality = data_quality_profile(df)
    if report.quality.get("invalid_phone_pct", 0) > 20:
        report.warnings.append("More than 20% of phone numbers look invalid – phone blocking will be weak.")
    if report.quality.get("invalid_email_pct", 0) > 20:
        report.warnings.append("More than 20% of emails look invalid – email blocking will be weak.")
    return report
