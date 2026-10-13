"""Synthetic INCOMING data generator.

Takes existing master records and produces incoming records that exercise
every test scenario of the project brief:

    S1  Exact match                  S7  Missing phone
    S2  Minor spelling variation     S8  Conflicting email
    S3  Name word order changed      S9  Two very similar candidates (ambiguous)
    S4  Phone format variation       S10 Completely new person (no match)
    S5  Address abbreviation         S11 Duplicate incoming records
    S6  Missing email                S12 Incorrect / noisy data

Because the generator KNOWS which master record each incoming record was
derived from, it also produces the ground-truth label for every record.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from data.master_generator import (
    SURNAMES, FIRST_NAMES_FEMALE, FIRST_NAMES_MALE, entity_id_for, find_twin_pairs, generate_person, make_twin,
)

SCENARIO_LABELS = {
    "exact": "S1 Exact match",
    "spelling": "S2 Minor spelling variation",
    "word_order": "S3 Name word order changed",
    "phone_format": "S4 Phone format variation",
    "address_abbrev": "S5 Address abbreviation",
    "missing_email": "S6 Missing email",
    "missing_phone": "S7 Missing phone",
    "conflicting_email": "S8 Conflicting email",
    "ambiguous": "S9 Two very similar candidates",
    "new_person": "S10 Completely new person",
    "duplicate": "S11 Duplicate incoming record",
    "noisy": "S12 Incorrect / noisy data",
}
MATCH_VARIATIONS = ["exact", "spelling", "word_order", "phone_format", "address_abbrev", "missing_email", "missing_phone"]
NOISY_VARIATIONS = ["conflicting_email", "noisy"]

ADDRESS_EXPANSIONS = [
    (r"\bMG Road\b", ["Mahatma Gandhi Road", "M.G. Road", "M G Rd", "MG Rd"]),
    (r"\bRoad\b", ["Rd", "Rd.", "Marg"]),
    (r"\bStreet\b", ["St", "St."]),
    (r"\bNagar\b", ["Ngr"]),
    (r"\bSector\b", ["Sec", "Sec."]),
    (r"\bApartments\b", ["Apts", "Apt"]),
]


@dataclass
class GenerationResult:
    records: list[dict]                          # incoming records (without incoming_id)
    ground_truth: list[dict]                     # {"row": i, "true_entity_id": .., "true_decision": ..}
    new_master_records: list[dict] = field(default_factory=list)   # twins created on demand
    scenario_counts: dict[str, int] = field(default_factory=dict)


# ------------------------------------------------------------- variations
def vary_case(name: str, rng: random.Random) -> str:
    choice = rng.randint(0, 5)
    if choice == 0:
        return name.upper()
    if choice == 1:
        return name.lower()
    if choice == 2:
        return re.sub(r" ", "  ", name, count=1)
    if choice == 3:
        return f"Mr. {name}" if rng.random() < 0.5 else f"Mrs. {name}"
    return name


def typo(word: str, rng: random.Random) -> str:
    if len(word) < 4:
        return word
    i = rng.randint(1, len(word) - 2)
    kind = rng.randint(0, 2)
    if kind == 0:                                   # swap adjacent letters
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == 1:                                   # drop a letter
        return word[:i] + word[i + 1:]
    vowels = "aeiou"                                # replace a vowel
    for j in range(i, len(word)):
        if word[j].lower() in vowels:
            repl = rng.choice([v for v in vowels if v != word[j].lower()])
            return word[:j] + (repl.upper() if word[j].isupper() else repl) + word[j + 1:]
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def spelling_variation(name: str | None, rng: random.Random) -> str | None:
    parts = (name or "").split()
    if not parts:
        return name
    idx = rng.randrange(len(parts))
    parts[idx] = typo(parts[idx], rng)
    return " ".join(parts)


def word_order_variation(name: str, rng: random.Random) -> str:
    parts = name.split()
    if len(parts) < 2:
        return name
    parts.reverse()
    return ", ".join(parts) if rng.random() < 0.3 else " ".join(parts)


def phone_format_variation(phone: str | None, rng: random.Random) -> str | None:
    if not phone or len(phone) < 10:
        return phone                      # nothing to reformat (missing or non-Indian identifier)
    formats = [
        f"+91 {phone}", f"+91-{phone}", f"0{phone}", f"+91 {phone[:5]} {phone[5:]}",
        f"{phone[:5]}-{phone[5:]}", f"(+91) {phone}", f"91{phone}", f"{phone[:3]} {phone[3:6]} {phone[6:]}",
    ]
    return rng.choice(formats)


def address_variation(address: str | None, rng: random.Random) -> str | None:
    if not address:
        return address
    out = address
    for pattern, options in ADDRESS_EXPANSIONS:
        if re.search(pattern, out):
            out = re.sub(pattern, rng.choice(options), out, count=1)
    if rng.random() < 0.5:
        out = out.replace(",", "")
    elif rng.random() < 0.5:
        out = re.sub(r"^(\d+) ", r"\1, ", out)
    return out


def corrupt_phone(phone: str, rng: random.Random, severe: bool = False) -> str:
    """Corrupt a phone number.

    mild   – change one of the first two digits (last 8 digits still agree → partial score 70)
    severe – change two digits in the tail (→ phone score 0, which triggers a name-vs-phone conflict)
    """
    if severe:
        positions = rng.sample(range(4, 10), 2)
        digits = list(phone)
        for p in positions:
            digits[p] = str((int(digits[p]) + rng.randint(1, 8)) % 10)
        return "".join(digits)
    i = rng.randint(0, 1)
    new_digit = str((int(phone[i]) + rng.randint(1, 8)) % 10)
    return phone[:i] + new_digit + phone[i + 1:]


def corrupt_email(email: str, rng: random.Random) -> str:
    user, _, domain = email.rpartition("@")
    return f"{typo(user, rng)}@{domain}"


def conflicting_email(name: str, rng: random.Random) -> str:
    first = name.split()[0].lower()
    return f"{rng.choice(['contact', 'info', 'office', 'mail', 'hello'])}.{first}{rng.randint(10, 999)}@{rng.choice(['protonmail.com', 'zoho.in', 'company-mail.in', 'live.in'])}"


# -------------------------------------------------------------- scenarios
def derive(master: dict, scenario: str, rng: random.Random) -> dict:
    """Create an incoming record from a master record according to the scenario."""
    rec = {k: master.get(k) for k in ("name", "email", "phone", "address", "date_of_birth", "company", "city", "state", "postal_code")}
    name = rec["name"] or "Unknown Person"

    if scenario == "exact":
        pass
    elif scenario == "spelling":
        rec["name"] = spelling_variation(name, rng)
        if rng.random() < 0.5:
            rec["phone"] = phone_format_variation(rec["phone"], rng)
    elif scenario == "word_order":
        rec["name"] = word_order_variation(name, rng)
    elif scenario == "phone_format":
        rec["name"] = vary_case(name, rng)
        rec["phone"] = phone_format_variation(rec["phone"], rng)
    elif scenario == "address_abbrev":
        rec["name"] = vary_case(name, rng)
        rec["address"] = address_variation(rec["address"], rng)
        if rng.random() < 0.5:
            rec["phone"] = phone_format_variation(rec["phone"], rng)
    elif scenario == "missing_email":
        rec["email"] = None
        rec["name"] = vary_case(name, rng)
        if rng.random() < 0.5:
            rec["address"] = address_variation(rec["address"], rng)
    elif scenario == "missing_phone":
        rec["phone"] = None
        rec["name"] = vary_case(name, rng)
        if rng.random() < 0.3:
            rec["date_of_birth"] = None
    elif scenario == "conflicting_email":
        rec["name"] = vary_case(name, rng)
        rec["email"] = conflicting_email(name, rng)
        if rng.random() < 0.5:
            rec["phone"] = phone_format_variation(rec["phone"], rng)
    elif scenario == "noisy":
        rec["name"] = spelling_variation(name, rng)
        rec["phone"] = corrupt_phone(rec["phone"], rng, severe=rng.random() < 0.5) if rec["phone"] else None
        rec["email"] = corrupt_email(rec["email"], rng) if rec["email"] else None
        rec["postal_code"] = str(rng.randint(100000, 999999))
        if rng.random() < 0.5:
            rec["address"] = spelling_variation(rec["address"], rng)
        if rng.random() < 0.3:
            rec["date_of_birth"] = None
    elif scenario == "ambiguous":
        # Sparse record: only name + location → two look-alike master records score the same
        rec["name"] = vary_case(name, rng)
        rec["email"] = None
        rec["phone"] = None
        rec["address"] = None
        rec["date_of_birth"] = None
        rec["company"] = None
    else:
        raise ValueError(f"Unknown scenario {scenario}")
    return rec


def new_person(rng: random.Random, used_emails: set[str], used_phones: set[str]) -> dict:
    """A person who does NOT exist in the master database."""
    person = generate_person(rng, used_emails, used_phones)
    # make sure the name is unusual enough to not collide with a real master name by accident
    if rng.random() < 0.5:
        person["name"] = f"{rng.choice(FIRST_NAMES_MALE + FIRST_NAMES_FEMALE)} {rng.choice(SURNAMES)}"
    return person


def _allocate(n: int, percentages: dict[str, float]) -> dict[str, int]:
    """Turn percentages into integer counts that sum exactly to n."""
    raw = {k: n * v / 100 for k, v in percentages.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = n - sum(counts.values())
    # distribute the remainder to the categories with the largest fractional part
    order = sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)
    for k in order[:remainder]:
        counts[k] += 1
    return counts


def generate_incoming(master_records: list[dict], n: int, match_pct: float = 70, no_match_pct: float = 15,
                      noisy_pct: float = 5, ambiguous_pct: float = 5, duplicate_pct: float = 5,
                      seed: int = 7, next_entity_index: int | None = None) -> GenerationResult:
    """Generate `n` incoming records with the requested scenario mix.

    Percentages must sum to 100.  Master records are plain dicts with entity_id.
    """
    total_pct = match_pct + no_match_pct + noisy_pct + ambiguous_pct + duplicate_pct
    if abs(total_pct - 100) > 0.01:
        raise ValueError(f"Percentages must sum to 100 (got {total_pct}).")
    if not master_records:
        raise ValueError("Master database is empty – generate master data first.")

    rng = random.Random(seed)
    counts = _allocate(n, {"match": match_pct, "no_match": no_match_pct, "noisy": noisy_pct,
                           "ambiguous": ambiguous_pct, "duplicate": duplicate_pct})

    used_emails = {m["email"] for m in master_records if m.get("email")}
    used_phones = {m["phone"] for m in master_records if m.get("phone")}
    masters = list(master_records)
    rng.shuffle(masters)
    master_iter = iter(masters)

    def next_master() -> dict:
        try:
            return next(master_iter)
        except StopIteration:
            return rng.choice(masters)

    records: list[dict] = []
    truth: list[dict] = []
    new_master: list[dict] = []
    scenario_counts: dict[str, int] = {}

    def add(rec: dict, scenario: str, true_entity: str | None, true_decision: str):
        rec["scenario"] = SCENARIO_LABELS[scenario]
        records.append(rec)
        truth.append({"row": len(records) - 1, "true_entity_id": true_entity, "true_decision": true_decision,
                      "scenario": SCENARIO_LABELS[scenario]})
        scenario_counts[SCENARIO_LABELS[scenario]] = scenario_counts.get(SCENARIO_LABELS[scenario], 0) + 1

    # --- matching records (cycle through the 7 variations)
    for i in range(counts["match"]):
        scenario = MATCH_VARIATIONS[i % len(MATCH_VARIATIONS)]
        m = next_master()
        add(derive(m, scenario, rng), scenario, m["entity_id"], "MATCH")

    # --- noisy records (alternate conflicting email / general noise)
    for i in range(counts["noisy"]):
        scenario = NOISY_VARIATIONS[i % len(NOISY_VARIATIONS)]
        m = next_master()
        add(derive(m, scenario, rng), scenario, m["entity_id"], "MATCH")

    # --- ambiguous records (need twin pairs; create twins on demand)
    pairs = find_twin_pairs(master_records)
    rng.shuffle(pairs)
    entity_index = next_entity_index or (len(master_records) + 1)
    for i in range(counts["ambiguous"]):
        if i < len(pairs):
            base = pairs[i][0]
        else:
            base = next_master()
            twin = make_twin(base, rng, used_emails, used_phones)
            twin = {**twin, "entity_id": entity_id_for(entity_index), "source": "synthetic-twin"}
            entity_index += 1
            new_master.append(twin)
        add(derive(base, "ambiguous", rng), "ambiguous", base["entity_id"], "MATCH")

    # --- completely new people
    for _ in range(counts["no_match"]):
        rec = new_person(rng, used_emails, used_phones)
        add(rec, "new_person", None, "NO_MATCH")

    # --- duplicates of records already in this batch
    candidates = [i for i, t in enumerate(truth) if t["true_decision"] == "MATCH"] or list(range(len(records)))
    for _ in range(counts["duplicate"]):
        if not records:
            break
        src = rng.choice(candidates)
        rec = {k: v for k, v in records[src].items() if k != "scenario"}
        if rng.random() < 0.5 and rec.get("name"):
            rec["name"] = vary_case(rec["name"], rng)
        add(rec, "duplicate", truth[src]["true_entity_id"], truth[src]["true_decision"])

    # shuffle so scenarios are interleaved like real data (deterministic given seed)
    order = list(range(len(records)))
    rng.shuffle(order)
    records = [records[i] for i in order]
    remap = {old: new for new, old in enumerate(order)}
    truth = sorted(({**t, "row": remap[t["row"]]} for t in truth), key=lambda t: t["row"])

    return GenerationResult(records=records, ground_truth=truth, new_master_records=new_master,
                            scenario_counts=scenario_counts)


def worked_example_incoming() -> dict:
    """The incoming side of the worked example used across the app."""
    return {
        "name": "RAHUL SHARMA",
        "email": "rahul.sharma@gmail.com",
        "phone": "+91 9876543210",
        "address": "12 Mahatma Gandhi Road Patna",
        "date_of_birth": "1988-05-14",
        "company": "TCS",
        "city": "Patna",
        "state": "Bihar",
        "postal_code": "800001",
    }
