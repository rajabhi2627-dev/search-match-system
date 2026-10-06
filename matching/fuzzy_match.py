"""STEP 5/6 – Fuzzy matching and field-level similarity.

Every field uses the comparison method that suits it:

* Name     – several RapidFuzz string metrics + Jaro-Winkler, blended.
* Address  – token based metrics (word order and abbreviations vary a lot).
* Company  – token set ratio + WRatio.
* Email    – exact → 100, else username similarity (70%) + domain (30%).
* Phone    – NOT text similarity: exact digits → 100, last-8 → 70, last-6 → 40.
* DOB      – exact → 100, different → 0, missing → not scored (None).

All functions return a dict with the final `score` AND the individual
sub-metrics, so the UI can show exactly how the number was produced.
"""
from __future__ import annotations

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

MATCH_FIELDS = ["name", "email", "phone", "address", "dob", "company"]

# Weights for blending the sub-metrics into one field score
NAME_BLEND = {"token_set_ratio": 0.5, "token_sort_ratio": 0.2, "jaro_winkler": 0.3}
ADDRESS_BLEND = {"token_set_ratio": 0.5, "token_sort_ratio": 0.3, "wratio": 0.2}
COMPANY_BLEND = {"token_set_ratio": 0.6, "wratio": 0.4}
EMAIL_BLEND = {"username": 0.7, "domain": 0.3}


def _r(x: float) -> float:
    return round(float(x), 1)


# -------------------------------------------------------------------- name
def name_similarity(a: str | None, b: str | None) -> dict:
    if not a or not b:
        return {"score": None, "reason": "missing"}
    metrics = {
        "wratio": fuzz.WRatio(a, b),
        "ratio": fuzz.ratio(a, b),
        "token_sort_ratio": fuzz.token_sort_ratio(a, b),
        "token_set_ratio": fuzz.token_set_ratio(a, b),
        "jaro_winkler": JaroWinkler.similarity(a, b) * 100,
    }
    score = sum(metrics[k] * w for k, w in NAME_BLEND.items())
    if a == b:
        score = 100.0
    return {"score": _r(score), **{k: _r(v) for k, v in metrics.items()}, "blend": NAME_BLEND}


# ----------------------------------------------------------------- address
def address_similarity(a: str | None, b: str | None) -> dict:
    if not a or not b:
        return {"score": None, "reason": "missing"}
    metrics = {
        "token_set_ratio": fuzz.token_set_ratio(a, b),
        "token_sort_ratio": fuzz.token_sort_ratio(a, b),
        "wratio": fuzz.WRatio(a, b),
    }
    score = sum(metrics[k] * w for k, w in ADDRESS_BLEND.items())
    if a == b:
        score = 100.0
    return {"score": _r(score), **{k: _r(v) for k, v in metrics.items()}, "blend": ADDRESS_BLEND}


# ----------------------------------------------------------------- company
def company_similarity(a: str | None, b: str | None) -> dict:
    if not a or not b:
        return {"score": None, "reason": "missing"}
    metrics = {"token_set_ratio": fuzz.token_set_ratio(a, b), "wratio": fuzz.WRatio(a, b)}
    score = sum(metrics[k] * w for k, w in COMPANY_BLEND.items())
    if a == b:
        score = 100.0
    return {"score": _r(score), **{k: _r(v) for k, v in metrics.items()}, "blend": COMPANY_BLEND}


# ------------------------------------------------------------------- email
def email_similarity(a: str | None, b: str | None) -> dict:
    if not a or not b:
        return {"score": None, "reason": "missing"}
    if a == b:
        return {"score": 100.0, "method": "exact", "username": 100.0, "domain": 100.0}
    ua, _, da = a.rpartition("@")
    ub, _, db = b.rpartition("@")
    username = fuzz.ratio(ua, ub)
    # Domains are identifiers, not free text: "protonmail.com" vs "gmail.com" must not score 70 for sharing "mail.com".
    domain = 100.0 if (da and da == db) else 0.0
    score = EMAIL_BLEND["username"] * username + EMAIL_BLEND["domain"] * domain
    method = "username+domain"
    # Different domain AND clearly different username → almost certainly a different mailbox.
    if domain < 100 and username < 80:
        score *= 0.75
        method = "username+domain (different-mailbox penalty ×0.75)"
    return {"score": _r(score), "method": method, "username": _r(username), "domain": _r(domain), "blend": EMAIL_BLEND}


# ------------------------------------------------------------------- phone
def phone_similarity(a: str | None, b: str | None) -> dict:
    """Digit-based comparison. Text fuzzy matching is meaningless for phones."""
    if not a or not b:
        return {"score": None, "reason": "missing"}
    if a == b:
        return {"score": 100.0, "method": "exact normalized digits"}
    if len(a) >= 8 and len(b) >= 8 and a[-8:] == b[-8:]:
        return {"score": 70.0, "method": "last 8 digits equal"}
    if len(a) >= 6 and len(b) >= 6 and a[-6:] == b[-6:]:
        return {"score": 40.0, "method": "last 6 digits equal"}
    return {"score": 0.0, "method": "different numbers"}


# --------------------------------------------------------------------- dob
def dob_similarity(a: str | None, b: str | None) -> dict:
    if not a or not b:
        return {"score": None, "reason": "missing"}
    return {"score": 100.0 if a == b else 0.0, "method": "exact date"}


# ------------------------------------------------------------ record level
def compute_field_scores(incoming: dict, candidate: dict) -> dict[str, dict]:
    """Field-level similarity between two *normalized* records.

    Returns {field: {"score": float|None, "incoming": str, "master": str, ...details}}
    """
    inc, mas = incoming["norm"], candidate["norm"]
    out = {
        "name": name_similarity(inc["name"], mas["name"]),
        "email": email_similarity(inc["email"], mas["email"]),
        "phone": phone_similarity(inc["phone"], mas["phone"]),
        "address": address_similarity(inc["address"], mas["address"]),
        "dob": dob_similarity(inc["dob"], mas["dob"]),
        "company": company_similarity(inc["company"], mas["company"]),
    }
    for field, details in out.items():
        details["incoming"] = inc.get(field)
        details["master"] = mas.get(field)
    return out


def scores_only(field_scores: dict[str, dict]) -> dict[str, float | None]:
    return {f: field_scores[f]["score"] for f in MATCH_FIELDS}
