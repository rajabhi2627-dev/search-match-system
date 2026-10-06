"""Generic helpers shared by all layers (config loading, formatting, IO)."""
from __future__ import annotations

import io
import json
import math
from datetime import datetime, date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

# Fields used for matching and for the merge comparison
MATCH_FIELDS = ["name", "email", "phone", "address", "dob", "company"]
RECORD_FIELDS = [
    "name",
    "email",
    "phone",
    "address",
    "date_of_birth",
    "company",
    "city",
    "state",
    "postal_code",
]
FIELD_LABELS = {
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "address": "Address",
    "dob": "Date of Birth",
    "date_of_birth": "Date of Birth",
    "company": "Company",
    "city": "City",
    "state": "State",
    "postal_code": "Postal Code",
}

DECISIONS = ["MATCH", "MANUAL_REVIEW", "NO_MATCH"]


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load config/config.yaml once (cached)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def is_missing(value: Any) -> bool:
    """True for None, NaN, empty / whitespace-only strings."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    try:
        if pd.isna(value):  # handles pd.NaT / pd.NA
            return True
    except (TypeError, ValueError):
        pass
    return False


def clean_value(value: Any) -> str | None:
    """Convert raw cell values to a stripped string (or None if missing)."""
    if is_missing(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def safe_div(numerator: float, denominator: float) -> float | None:
    """Division that returns None instead of raising on zero denominators."""
    if not denominator:
        return None
    return numerator / denominator


def pct(value: float | None, digits: int = 1) -> str:
    """Format a 0-100 value as a percentage string, or n/a."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:.{digits}f}%"


def fmt_score(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def json_loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def df_to_excel_bytes(frames: dict[str, pd.DataFrame]) -> bytes:
    """Write one or more DataFrames to an in-memory .xlsx file."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, df in frames.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)
    buffer.seek(0)
    return buffer.getvalue()


def chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def rag_colour(status: str | None) -> str:
    return {"GREEN": "#2e7d32", "AMBER": "#f9a825", "RED": "#c62828"}.get(status or "", "#9e9e9e")


def rag_emoji(status: str | None) -> str:
    return {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(status or "", "⚪")


def decision_emoji(decision: str | None) -> str:
    return {"MATCH": "✅", "MANUAL_REVIEW": "🟡", "NO_MATCH": "❌"}.get(decision or "", "⚪")


def confidence_emoji(level: str | None) -> str:
    return {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(level or "", "⚪")
