"""Page 14 – Methodology (the algorithm explained step by step, with a flow diagram and a live worked example)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.common import df, get_active_config, how_it_works, page_header
from data.incoming_generator import worked_example_incoming
from data.master_generator import WORKED_EXAMPLE
from matching.blocking import BlockingIndex
from matching.pipeline import MatchEngine
from matching.preprocessing import normalization_table, normalize_record
from matching.scoring import calculation_rows

FLOW = """
digraph G {
  rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#e3f2fd", fontname="Helvetica", fontsize=11];
  M [label="MASTER DATABASE"]; I [label="INCOMING DATA"]; N [label="1. NORMALIZATION"]; B [label="2–3. MULTI-PASS BLOCKING\\n(candidate generation)"];
  E [label="4. EXACT MATCHING"]; F [label="5. FUZZY MATCHING\\n(RapidFuzz, Jaro-Winkler)"]; S [label="6. FIELD-LEVEL SIMILARITY"];
  W [label="7. WEIGHTED OVERALL SCORE\\n(missing fields re-normalized)"]; C [label="8. CONFLICT DETECTION"]; R [label="9. TOP-N RANKING"];
  G [label="10. SCORE GAP / AMBIGUITY"]; K [label="11. CONFIDENCE"]; D [label="12. FINAL DECISION", fillcolor="#fff8e1"];
  MA [label="MATCH", fillcolor="#c8e6c9"]; MR [label="MANUAL REVIEW", fillcolor="#ffecb3"]; NM [label="NO MATCH", fillcolor="#ffcdd2"];
  MG [label="13. OPTIONAL MERGE"]; P [label="14. PERFORMANCE TRACKING"]; DB [label="DASHBOARD"];
  M -> B; I -> N -> B -> E -> F -> S -> W -> C -> R -> G -> K -> D; D -> MA; D -> MR; D -> NM; MA -> MG; MR -> MG; MG -> P; NM -> P; P -> DB;
}
"""

STEPS = [
    ("STEP 1 – Normalization", "Raw values are cleaned so that equivalent values look identical: lower-case, remove punctuation, collapse spaces, "
     "drop titles (Mr/Mrs/Dr), keep only phone digits and remove the +91 / 0 prefix, standardise address abbreviations "
     "(Road→Rd, Street→St, Mahatma Gandhi→MG). The original value is always kept next to the normalized one."),
    ("STEP 2 – Blocking", "Instead of comparing an incoming record with every master record, the system first creates a smaller candidate pool "
     "using phone, email, city, postal code and name-based rules. Six passes: exact phone, exact email, postal code + surname, city + surname, "
     "phonetic (Soundex) surname + city, first-name token + city."),
    ("STEP 3 – Candidate generation", "Candidates from all passes are combined, duplicates removed, and the system remembers WHICH passes produced "
     "each candidate (e.g. 'Phone block AND City + surname block'). With 5,000 master records a typical pool is 5–20 candidates (≈99.7% reduction)."),
    ("STEP 4 – Exact matching", "Exact rules on normalized values: email, phone, name + DOB, phone + DOB, email + name. A single matching field is an "
     "indicator; a matching COMBINATION is a strong signal. No rule merges automatically."),
    ("STEP 5 – Fuzzy matching", "The system calculates similarity between fields using appropriate algorithms such as Jaro-Winkler, token-based "
     "similarity (Token Sort / Token Set) and edit-distance-based methods (Ratio, WRatio). Names blend Token Set (50%), Token Sort (20%) and "
     "Jaro-Winkler (30%). Addresses and companies use token metrics. Email compares username and domain. Phone compares digits only (exact / last 8 / last 6). "
     "DOB is exact (100) or different (0)."),
    ("STEP 6 – Field-level scoring", "Each field gets a 0–100 score. A field present in only one record is NOT scored (None) rather than 0."),
    ("STEP 7 – Weighted overall score", "Overall = Σ(score × weight) / Σ(weights of available fields). Default weights: Name 25, Email 25, Phone 25, "
     "Address 15, DOB 5, Company 5. Missing fields are dropped and the remaining weights are re-normalized to 100%. Optional rare-value weighting "
     "multiplies each weight by a capped information factor (0.7–1.5): agreeing on a phone number only one entity has is worth more than agreeing on a common value."),
    ("STEP 8 – Conflict detection", "The system does not rely only on the overall score. It checks whether important fields disagree strongly: "
     "strong name but different phone, exact phone but different email, exact email but different phone, same DOB but different name (all CRITICAL); "
     "strong name but different DOB, same address but different name (WARNING). A critical conflict always blocks automatic MATCH."),
    ("STEP 9 – Top-N ranking", "Candidates are sorted by overall score (ties broken by entity ID for determinism) and the top 5 are returned with all component scores."),
    ("STEP 10 – Score gap", "The difference between the best and second-best candidate indicates whether the best match is clearly superior or ambiguous. "
     "Gap = best − second (second = 0 when there is only one candidate)."),
    ("STEP 11 – Confidence", "A point system independent of the raw score: similarity level, number of strongly matching fields, critical identifier "
     "agreement, score gap, data completeness, minus penalties for conflicts → HIGH (≥70) / MEDIUM (≥45) / LOW."),
    ("STEP 12 – Final decision", "score ≥ 85 AND gap ≥ 5 AND no critical conflict → MATCH · 65 ≤ score < 85 → MANUAL_REVIEW · score ≥ 85 but conflict or "
     "gap < 5 → MANUAL_REVIEW · score < 65 → NO_MATCH. Thresholds are prototype settings stored in the algorithm version."),
    ("STEP 13 – Merge", "After a MATCH the user compares master vs incoming field by field, chooses which value survives and confirms or rejects. "
     "Old and new values are stored; merges can be reversed."),
    ("STEP 14 – Performance tracking", "Every run stores counts, Match Rate, HIT Rate, Manual Review Rate, candidate reduction and – when ground truth "
     "exists – precision, recall, F1, FPR, FNR, accuracy. Disputes and merge errors are tracked from human actions. Versions are compared and regression-tested."),
]


def render() -> None:
    page_header("Methodology", "The complete Search, Match & Merge algorithm explained in simple language.")
    how_it_works("Scroll through the 14 steps, then watch the worked example (Rahul Sharma) flow through the live engine at the bottom.", expanded=False)

    st.subheader("Flow diagram")
    try:
        st.graphviz_chart(FLOW, width="stretch")
    except Exception:
        st.code("MASTER DATABASE + INCOMING DATA → NORMALIZATION → BLOCKING → EXACT → FUZZY → FIELD SCORES → WEIGHTED SCORE → CONFLICTS → "
                "TOP-N → SCORE GAP → CONFIDENCE → DECISION → (MATCH | MANUAL REVIEW | NO MATCH) → OPTIONAL MERGE → PERFORMANCE TRACKING → DASHBOARD")

    st.subheader("The 14 steps")
    for title, text in STEPS:
        with st.expander(title):
            st.write(text)

    st.subheader("Worked example – live")
    st.caption("The same example is used across the application. Master C01023 vs an incoming record with formatting differences.")
    c1, c2 = st.columns(2)
    inc = worked_example_incoming()
    with c1:
        st.markdown("**Master (entity C01023)**")
        df(pd.DataFrame({"Field": list(WORKED_EXAMPLE), "Value": list(WORKED_EXAMPLE.values())}))
    with c2:
        st.markdown("**Incoming**")
        df(pd.DataFrame({"Field": list(inc), "Value": list(inc.values())}))

    cfg = get_active_config()
    engine = MatchEngine(cfg, BlockingIndex([{"entity_id": "C01023", **WORKED_EXAMPLE}]))
    outcome = engine.match_record(inc)
    best = outcome.best
    st.markdown("**Step 1 – Normalization makes the fields comparable**")
    df(pd.DataFrame(normalization_table(outcome.normalized)))
    st.markdown("**Step 2–3 – Blocking identifies C01023 as a candidate via:** " + ", ".join(f"`{p}`" for p in best.blocking_methods))
    st.markdown("**Step 4 – Exact rules fired:** " + ", ".join(r["label"] for r in best.exact_rules))
    st.markdown("**Step 5–7 – Field scores and weighted calculation**")
    df(pd.DataFrame(calculation_rows(best.breakdown, best.field_scores)))
    st.markdown(f"**Step 8 – Conflicts:** {'none' if not best.conflicts else best.conflicts}")
    st.markdown(f"**Step 10 – Score gap:** {outcome.score_gap} (only one candidate in this mini-example, so second = 0)")
    st.markdown(f"**Step 11 – Confidence:** {outcome.confidence} ({outcome.confidence_points} points)")
    st.markdown(f"**Step 12 – Decision:** `{outcome.decision}`")
    st.info(outcome.reason)
    st.caption("Open *Search & Match* → *Load worked example* to run the same record against the full master database.")
