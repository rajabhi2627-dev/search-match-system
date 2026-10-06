"""AlgorithmConfig – the complete, versioned parameter set of the matcher.

Every matching run is executed with exactly one AlgorithmConfig.  The same
object is stored as a row in `algorithm_versions`, so a run can always be
reproduced later.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from utils.helpers import MATCH_FIELDS, load_config

DEFAULT_BLOCKING_PASSES = [
    "phone",
    "email",
    "postal_surname",
    "city_surname",
    "phonetic_surname_city",
    "first_token_city",
]


@dataclass
class AlgorithmConfig:
    version_name: str = "1.0"
    weights: dict[str, float] = field(
        default_factory=lambda: {"name": 25, "email": 25, "phone": 25, "address": 15, "dob": 5, "company": 5}
    )
    match_threshold: float = 85.0
    manual_review_threshold: float = 65.0
    ambiguity_gap_threshold: float = 5.0
    blocking_passes: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKING_PASSES))
    rare_value_weighting: bool = False
    top_n: int = 5
    description: str = ""
    full_scan_if_master_below: int = 50

    # ------------------------------------------------------------------ build
    @classmethod
    def from_yaml(cls) -> "AlgorithmConfig":
        cfg = load_config()["algorithm"]
        return cls(
            version_name=str(cfg.get("default_version_name", "1.0")),
            weights={k: float(v) for k, v in cfg["weights"].items()},
            match_threshold=float(cfg["thresholds"]["match"]),
            manual_review_threshold=float(cfg["thresholds"]["manual_review"]),
            ambiguity_gap_threshold=float(cfg["thresholds"]["ambiguity_gap"]),
            blocking_passes=list(cfg.get("blocking_passes", DEFAULT_BLOCKING_PASSES)),
            rare_value_weighting=bool(cfg.get("rare_value_weighting", False)),
            top_n=int(cfg.get("top_n", 5)),
            description=str(cfg.get("description", "")),
            full_scan_if_master_below=int(cfg.get("full_scan_if_master_below", 50)),
        )

    @classmethod
    def from_db_row(cls, row) -> "AlgorithmConfig":
        """Build from an `AlgorithmVersion` ORM row."""
        from utils.helpers import json_loads

        passes = json_loads(row.blocking_rules, default=None) or list(DEFAULT_BLOCKING_PASSES)
        return cls(
            version_name=row.version_name,
            weights={
                "name": row.name_weight,
                "email": row.email_weight,
                "phone": row.phone_weight,
                "address": row.address_weight,
                "dob": row.dob_weight,
                "company": row.company_weight,
            },
            match_threshold=row.match_threshold,
            manual_review_threshold=row.manual_review_threshold,
            ambiguity_gap_threshold=row.ambiguity_gap_threshold,
            blocking_passes=passes,
            rare_value_weighting=bool(row.rare_value_weighting),
            top_n=int(row.top_n or 5),
            description=row.description or "",
            full_scan_if_master_below=int(load_config()["algorithm"].get("full_scan_if_master_below", 50)),
        )

    # -------------------------------------------------------------- validate
    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty list = valid)."""
        problems: list[str] = []
        total = sum(self.weights.get(f, 0) for f in MATCH_FIELDS)
        if abs(total - 100) > 0.01:
            problems.append(f"Weights must sum to 100 (currently {total:.1f}).")
        if any(self.weights.get(f, 0) < 0 for f in MATCH_FIELDS):
            problems.append("Weights cannot be negative.")
        if not (0 <= self.manual_review_threshold < self.match_threshold <= 100):
            problems.append("Thresholds must satisfy 0 <= manual review < match <= 100.")
        if self.ambiguity_gap_threshold < 0:
            problems.append("Ambiguity gap threshold cannot be negative.")
        if not self.blocking_passes:
            problems.append("At least one blocking pass must be enabled.")
        if self.top_n < 1:
            problems.append("Top-N must be at least 1.")
        return problems

    def to_dict(self) -> dict:
        return asdict(self)

    def signature(self) -> dict:
        """The parameters that define the *behaviour* of a version."""
        return {
            "weights": dict(self.weights),
            "match_threshold": self.match_threshold,
            "manual_review_threshold": self.manual_review_threshold,
            "ambiguity_gap_threshold": self.ambiguity_gap_threshold,
            "blocking_passes": list(self.blocking_passes),
            "rare_value_weighting": self.rare_value_weighting,
            "top_n": self.top_n,
        }
