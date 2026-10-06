"""STEP 1 – Data normalization.

Raw values are messy ("RAHUL  SHARMA", "+91-98765 43210", "12, M.G. Road").
Normalization converts them into a canonical form so that two values that
*mean* the same thing also *look* the same.

Rules
-----
* The ORIGINAL value is always kept – we never overwrite source data.
* Normalization is deterministic: the same input always gives the same output.
* Each field has its own rules because a phone number and an address need
  very different treatment.
"""
from __future__ import annotations

import re
from datetime import datetime

from utils.helpers import clean_value

# ---------------------------------------------------------------- constants
NAME_TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "prof", "sri", "kumari", "md"}

ADDRESS_ABBREVIATIONS: list[tuple[str, str]] = [
    # (pattern, replacement) – applied in order, on lower-cased text with punctuation removed
    (r"\bmahatma gandhi\b", "mg"),
    (r"\bm g\b", "mg"),
    (r"\broad\b", "rd"),
    (r"\bstreet\b", "st"),
    (r"\blane\b", "ln"),
    (r"\bavenue\b", "ave"),
    (r"\bmarg\b", "rd"),
    (r"\bapartments?\b", "apt"),
    (r"\bflat no\b", "flat"),
    (r"\bhouse no\b", "h no"),
    (r"\bsector\b", "sec"),
    (r"\bblock\b", "blk"),
    (r"\bnagar\b", "ngr"),
    (r"\bcolony\b", "col"),
    (r"\bopposite\b", "opp"),
    (r"\bnear\b", "nr"),
    (r"\bfloor\b", "fl"),
]

COMPANY_SUFFIXES = {"pvt", "ltd", "limited", "private", "llp", "inc", "co", "corp", "corporation", "company", "technologies", "tech"}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"]


# ------------------------------------------------------------- primitives
def _basic_clean(text: str) -> str:
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_name(value) -> str | None:
    """lowercase → remove punctuation → drop titles → collapse whitespace."""
    raw = clean_value(value)
    if raw is None:
        return None
    text = _basic_clean(raw)
    tokens = [t for t in text.split() if t not in NAME_TITLES]
    return " ".join(tokens) or None


def name_tokens(norm_name: str | None) -> list[str]:
    return norm_name.split() if norm_name else []


def surname(norm_name: str | None) -> str | None:
    """Last token of the normalized name (first token if only one token)."""
    tokens = name_tokens(norm_name)
    return tokens[-1] if tokens else None


def first_token(norm_name: str | None) -> str | None:
    tokens = name_tokens(norm_name)
    return tokens[0] if tokens else None


def normalize_email(value) -> str | None:
    raw = clean_value(value)
    if raw is None:
        return None
    text = re.sub(r"\s+", "", raw).lower()
    return text or None


def email_parts(norm_email: str | None) -> tuple[str | None, str | None]:
    if not norm_email or "@" not in norm_email:
        return (norm_email, None)
    user, _, domain = norm_email.rpartition("@")
    return (user or None, domain or None)


def normalize_phone(value) -> str | None:
    """Keep digits only and strip the Indian country code / trunk prefix.

    9876543210, +91 9876543210, 0091-98765-43210, 09876543210  → 9876543210
    """
    raw = clean_value(value)
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if len(digits) > 10 and digits.startswith("0091"):
        digits = digits[4:]
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) > 10:          # unknown prefix – keep the national part
        digits = digits[-10:]
    return digits


def normalize_address(value) -> str | None:
    raw = clean_value(value)
    if raw is None:
        return None
    text = _basic_clean(raw)
    for pattern, replacement in ADDRESS_ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    return _SPACE_RE.sub(" ", text).strip() or None


def normalize_company(value) -> str | None:
    raw = clean_value(value)
    if raw is None:
        return None
    text = _basic_clean(raw)
    tokens = [t for t in text.split() if t not in COMPANY_SUFFIXES]
    return " ".join(tokens) or _basic_clean(raw) or None


def normalize_dob(value) -> str | None:
    """Return ISO date (YYYY-MM-DD) or None if the value cannot be parsed."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    raw = clean_value(value)
    if raw is None:
        return None
    raw = raw.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}", raw) else raw
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_text(value) -> str | None:
    raw = clean_value(value)
    return _basic_clean(raw) or None if raw else None


def normalize_postal(value) -> str | None:
    raw = clean_value(value)
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits or None


def soundex(word: str | None) -> str | None:
    """Classic Soundex phonetic code (e.g. Sharma → S650, Sharmah → S650)."""
    if not word:
        return None
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return None
    codes = {
        **dict.fromkeys("bfpv", "1"),
        **dict.fromkeys("cgjkqsxz", "2"),
        **dict.fromkeys("dt", "3"),
        "l": "4",
        **dict.fromkeys("mn", "5"),
        "r": "6",
    }
    first = word[0].upper()
    encoded = first
    last_code = codes.get(word[0], "")
    for ch in word[1:]:
        code = codes.get(ch, "")
        if code and code != last_code:
            encoded += code
        if ch not in "hw":
            last_code = code
    return (encoded + "000")[:4]


# ------------------------------------------------------------ record level
def normalize_record(record: dict) -> dict:
    """Normalize one record.

    Returns
    -------
    {
      "original": {...raw values...},
      "norm":     {name, email, phone, address, dob, company, city, state, postal_code},
      "derived":  {surname, first_token, surname_soundex, email_user, email_domain}
    }
    """
    original = {k: clean_value(record.get(k)) for k in (
        "entity_id", "incoming_id", "name", "email", "phone", "address",
        "date_of_birth", "company", "city", "state", "postal_code",
    )}
    norm = {
        "name": normalize_name(record.get("name")),
        "email": normalize_email(record.get("email")),
        "phone": normalize_phone(record.get("phone")),
        "address": normalize_address(record.get("address")),
        "dob": normalize_dob(record.get("date_of_birth") or record.get("dob")),
        "company": normalize_company(record.get("company")),
        "city": normalize_text(record.get("city")),
        "state": normalize_text(record.get("state")),
        "postal_code": normalize_postal(record.get("postal_code")),
    }
    user, domain = email_parts(norm["email"])
    derived = {
        "surname": surname(norm["name"]),
        "first_token": first_token(norm["name"]),
        "surname_soundex": soundex(surname(norm["name"])),
        "email_user": user,
        "email_domain": domain,
    }
    return {"original": original, "norm": norm, "derived": derived}


def normalization_table(normalized: dict) -> list[dict]:
    """Rows of (field, original, normalized) for display in the UI."""
    labels = {
        "name": "Name", "email": "Email", "phone": "Phone", "address": "Address",
        "dob": "Date of Birth", "company": "Company", "city": "City",
        "state": "State", "postal_code": "Postal Code",
    }
    rows = []
    for key, label in labels.items():
        orig_key = "date_of_birth" if key == "dob" else key
        rows.append({
            "Field": label,
            "Original": normalized["original"].get(orig_key) or "",
            "Normalized": normalized["norm"].get(key) or "",
        })
    return rows
