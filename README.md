# Search, Match & Merge – Algorithm with Performance Monitoring (Phase 1)

A complete, working prototype of a **deterministic, explainable Search, Match & Merge engine** with a relational database, synthetic data generators, Excel/CSV batch processing, human review and merge workflows, algorithm versioning, regression and stability testing, and an interactive performance dashboard.

> **Scope control.** This is Phase 1 of a two-phase project. It contains **no AI agent, no LLM, no RAG, no generative component**. Everything is rule-based, data-driven and measurable. Phase 2 (an agentic monitoring & validation layer *around* this engine) will be built separately and will consume the metrics this system produces.
>
> **Demo application using synthetic data only.** No real customer information is used anywhere.

---

## Table of contents

1. [Project objective](#1-project-objective)
2. [Business problem](#2-business-problem)
3. [Architecture](#3-architecture)
4. [Database](#4-database)
5. [Data generation](#5-data-generation)
6. [Normalization](#6-normalization)
7. [Blocking (candidate generation)](#7-blocking-candidate-generation)
8. [Exact matching](#8-exact-matching)
9. [Fuzzy matching](#9-fuzzy-matching)
10. [Scoring](#10-scoring)
11. [Conflict detection](#11-conflict-detection)
12. [Ranking and score gap](#12-ranking-and-score-gap)
13. [Confidence](#13-confidence)
14. [Decision rules](#14-decision-rules)
15. [Merge process](#15-merge-process)
16. [Performance metrics](#16-performance-metrics)
17. [Ground truth](#17-ground-truth)
18. [Algorithm versioning](#18-algorithm-versioning)
19. [Regression and stability testing](#19-regression-and-stability-testing)
20. [Dashboard](#20-dashboard)
21. [Installation](#21-installation)
22. [Running locally](#22-running-locally)
23. [Tests](#23-tests)
24. [GitHub setup](#24-github-setup)
25. [Deployment](#25-deployment)
26. [Demo walkthrough](#26-demo-walkthrough)
27. [Limitations](#27-limitations)
28. [Future improvements](#28-future-improvements)
29. [Glossary](#29-glossary)

---

## 1. Project objective

Build a platform that can:

* maintain a master database of customers/entities,
* generate synthetic incoming records with one click or accept them through Excel/CSV upload,
* search the master database efficiently (blocking), perform exact and fuzzy matching with multiple similarity algorithms,
* compute field-level and weighted overall scores, detect conflicts, rank the top-5 candidates, detect ambiguity,
* decide **MATCH / MANUAL_REVIEW / NO_MATCH** and **explain** every decision,
* allow controlled merging with full history,
* track algorithm versions and historical performance, compare versions, and
* present everything in a professional dashboard.

## 2. Business problem

Organisations receive the same person through many channels (branch forms, web, partners, uploads). Names are spelled differently, phones carry `+91` or `0` prefixes, addresses are abbreviated. If records are not matched, duplicates accumulate (wrong balances, duplicate KYC, mis-directed communication). If records are matched *wrongly*, two different people are merged – a serious data-protection and operational risk.

A Search, Match & Merge algorithm therefore needs two things: a strong, explainable matching logic **and** a monitoring framework that measures how well it performs over time (HIT rate, precision, recall, false positives/negatives, manual review rate, dispute rate, merge error rate) and detects degradation when the logic changes.

## 3. Architecture

```
MASTER DATABASE ──┐
                  ├─► NORMALIZATION ─► MULTI-PASS BLOCKING ─► EXACT MATCHING ─► FUZZY MATCHING
INCOMING DATA ────┘                                                                 │
                                                                                    ▼
DASHBOARD ◄─ PERFORMANCE TRACKING ◄─ OPTIONAL MERGE ◄─ MATCH / REVIEW / NO MATCH ◄─ FINAL DECISION
                                                                                    ▲
                      FIELD-LEVEL SIMILARITY ─► WEIGHTED SCORE ─► CONFLICT DETECTION ─► TOP-N RANKING ─► SCORE GAP ─► CONFIDENCE
```

Layers (each a Python package, independent and unit-testable):

| Layer | Package | Responsibility |
|---|---|---|
| UI | `dashboard/`, `app.py` | 14 Streamlit pages; thin – they call the layers below |
| Workflows | `workflows/runner.py` | Generate master/incoming data, run a batch, store results (shared by UI and seed script) |
| Matching engine | `matching/` | Pure functions: normalize → block → exact → fuzzy → score → conflicts → rank → gap → confidence → decide → explain |
| Data | `data/` | Synthetic generators, Excel/CSV loader, validators / data-quality profile |
| Performance | `performance/` | Metrics, ground-truth evaluation, version comparison, regression & stability tests, RAG thresholds |
| Database | `database/` | SQLAlchemy models, connection, repository (all SQL in one place), seed script |
| Utilities | `utils/`, `config/config.yaml` | Config loading, helpers, logging |

The engine (`matching/pipeline.py: MatchEngine`) is a pure function of *(algorithm version, master index, incoming record)*. It never touches the database, so the same engine is reused for Search, Batch Upload, regression tests and stability tests – and the same input always gives the same output.

## 4. Database

SQLite file `storage/smm.db` (created automatically; git-ignored). Tables (SQLAlchemy ORM in `database/models.py`):

| Table | Purpose | Key fields |
|---|---|---|
| `master_entities` | Golden records | entity_id, name, email, phone, address, date_of_birth, company, city, state, postal_code, source, created_at, updated_at |
| `incoming_records` | Records to match | incoming_id, same fields, received_at, source, batch_id, scenario |
| `match_candidates` | Every top-N candidate | run_id, incoming_id, entity_id, candidate_rank, name/email/phone/address/dob/company_score, overall_score, score_gap, conflict_flag, critical_conflict, confidence, decision, blocking_methods, exact_rules, details_json, algorithm_version |
| `match_results` | One final decision per incoming per run | run_id, batch_id, incoming_id, entity_id, overall_score, score_gap, decision, confidence, conflict_flag, reason, decision_rule, candidate_pool_size, master_size, algorithm_version, matched_at |
| `merge_history` | CONFIRMED / REJECTED / REVERSED merges | incoming_id, entity_id, merge_decision, old_values, new_values, reason, is_error, actor |
| `algorithm_versions` | Immutable parameter sets | version_name, six weights, match/manual_review/ambiguity_gap thresholds, blocking_rules, rare_value_weighting, top_n, description, is_active |
| `performance_runs` | One row per run | run_id, batch_id, algorithm_version, totals, match_rate, hit_rate, precision, recall, f1_score, accuracy, FPR, FNR, manual_review_rate, dispute_rate, merge_error_rate, candidate_reduction_pct, tp/fp/fn/tn, data_quality_json |
| `human_review` | Reviewer decisions | incoming_id, predicted_entity_id, actual_entity_id, review_decision, review_reason, reviewer, is_dispute |
| `audit_logs` | Who did what | timestamp, actor, action_type, record_ref, algorithm_version, old_value, new_value, details |
| `ground_truth` (support) | Labels | incoming_id, true_entity_id, true_decision, source |
| `monitoring_thresholds` (support) | Green/Amber/Red | metric, direction, green, amber |

`run_id` on results/candidates lets the same batch be re-run under a new algorithm version without overwriting history.

## 5. Data generation

**Master generator** (`data/master_generator.py`) – Indian-style synthetic names, 10-digit mobiles, emails, street addresses, cities with states and PIN prefixes, companies, DOBs. Seeded (`seed` → identical data). A configurable share (default 2 %) of records get a *near twin* (same name + city, different identifiers) so ambiguous matches exist. The worked example **Rahul Sharma · 9876543210 · rahul.sharma@gmail.com · 12 MG Road, Patna** is always inserted (entity `C01023` when ≥ 1,023 records).

**Incoming generator** (`data/incoming_generator.py`) – derives records from master records and intentionally produces the 12 test scenarios:

| # | Scenario | How it is produced | Expected engine behaviour |
|---|---|---|---|
| S1 | Exact match | identical copy | MATCH, score 100 |
| S2 | Minor spelling variation | one typo in the name | MATCH (name ≈ 90+) |
| S3 | Name word order changed | "Sharma Rahul" / "Kumar, Nikhil" | MATCH (token-based metrics) |
| S4 | Phone format variation | `+91 …`, `0…`, spaces, dashes | MATCH (normalization) |
| S5 | Address abbreviation | MG Road ↔ Mahatma Gandhi Road, Rd/St | MATCH (abbreviation map) |
| S6 | Missing email | email blank | MATCH, weights re-normalized |
| S7 | Missing phone | phone blank | MATCH, weights re-normalized |
| S8 | Conflicting email | same person, new mailbox | MANUAL_REVIEW (critical conflict phone vs email) |
| S9 | Two very similar candidates | sparse record (name + city) with a twin in master | MANUAL_REVIEW (gap 0) |
| S10 | Completely new person | brand-new identity | NO_MATCH |
| S11 | Duplicate incoming records | copy of another row in the batch | same as original |
| S12 | Incorrect / noisy data | typos, corrupted phone, wrong PIN | MATCH or MANUAL_REVIEW depending on severity |

Because the generator knows the source record, it writes a **ground-truth label** for every row, which is what makes precision/recall measurable in the demo.

## 6. Normalization

`matching/preprocessing.py` – original values are always kept next to the normalized ones.

| Field | Rules |
|---|---|
| Name | lower-case, remove punctuation, collapse whitespace, drop titles (Mr, Mrs, Dr, Shri…), tokenize → surname = last token, Soundex of surname |
| Email | lower-case, remove all whitespace, split username / domain |
| Phone | digits only; strip `0091`, `91` (12 digits), leading `0` (11 digits); keep last 10 |
| Address | lower-case, remove punctuation, standardise abbreviations (Mahatma Gandhi → MG, Road → Rd, Street → St, Lane → Ln, Nagar → Ngr, Sector → Sec…) |
| DOB | parse many formats → ISO `YYYY-MM-DD` |
| Company | lower-case, drop legal suffixes (Pvt, Ltd, Limited, LLP…) |

Example: `12 MG Road, Patna`, `12 Mahatma Gandhi Road Patna`, `12, M.G. Road, Patna` all become `12 mg rd patna`.

## 7. Blocking (candidate generation)

> Blocking reduces the number of records that need detailed comparison. Instead of comparing one incoming record against 10,000 master records, the system first narrows the search to a smaller candidate set.

`matching/blocking.py` builds an in-memory index of the master data once and then, per incoming record, looks up candidates in six passes:

| Pass | Key |
|---|---|
| 1 | exact normalized phone |
| 2 | exact normalized email |
| 3 | postal code + surname |
| 4 | city + surname |
| 5 | city + Soundex(surname) (catches Sharma/Sharmah) |
| 6 | city + first-name token |

Candidates from all passes are unioned, duplicates removed, and **the passes that produced each candidate are stored** ("Phone block AND City + surname block"). The UI shows *master records → candidates after blocking → candidate reduction %* (typically 99.7 % with 5,000 records). For tiny master sets (< 50) a full scan is used because blocking adds nothing.

## 8. Exact matching

`matching/exact_match.py` – rules on normalized values: exact email; exact phone; name + DOB; phone + DOB; email + name. A **single** matching field is only an *indicator*; a matching **combination** is a *strong* signal used by the confidence calculation. No rule merges automatically.

## 9. Fuzzy matching

`matching/fuzzy_match.py` – RapidFuzz; every function returns the sub-metrics so the UI can show how a number was produced.

| Field | Method |
|---|---|
| Name | WRatio, Ratio, Token Sort Ratio, Token Set Ratio, Jaro-Winkler; score = 0.5·TokenSet + 0.2·TokenSort + 0.3·Jaro-Winkler |
| Address | 0.5·TokenSet + 0.3·TokenSort + 0.2·WRatio |
| Company | 0.6·TokenSet + 0.4·WRatio |
| Email | exact → 100; else 0.7·username similarity + 0.3·domain (domain is exact-or-not); ×0.75 when both domain and username differ |
| Phone | **not text similarity**: exact digits → 100, last 8 digits equal → 70, last 6 → 40, else 0 |
| DOB | exact → 100, different → 0, missing → not scored |

## 10. Scoring

`matching/scoring.py`

```
Overall = Σ (field score × effective weight) / Σ effective weights
```

Default weights: Name 25, Email 25, Phone 25, Address 15, DOB 5, Company 5 (configurable; must sum to 100).

**Missing fields are not zero.** If DOB is missing in either record, its weight is removed and the remaining weights are re-normalized to 100 %. Example from the UI: name 92, email 100, phone 100, address 82, DOB 100, company missing → (92·25 + 100·25 + 100·25 + 82·15 + 100·5) / 95 = **95.1**.

**Rare-value / information weighting (optional, OFF by default).** Agreement on a phone number that only one master record has is more informative than agreement on a value shared by thousands. When ON, each field weight is multiplied by `clamp(0.7 + 0.2·log10(N / frequency), 0.7, 1.5)` and re-normalized. The cap guarantees it can never override the configured weights.

## 11. Conflict detection

`matching/conflict_detection.py` – the overall score can hide a serious disagreement, so field pairs are checked:

| Rule | Severity |
|---|---|
| name ≥ 90 and phone ≤ 30 | CRITICAL |
| phone = 100 and email ≤ 30 | CRITICAL ("email differs significantly from other fields") |
| email = 100 and phone ≤ 30 | CRITICAL |
| DOB = 100 and name ≤ 50 | CRITICAL |
| name ≥ 90 and DOB = 0 | WARNING |
| name ≥ 90, email ≤ 30, phone missing | WARNING |
| address ≥ 90 and name ≤ 50 | WARNING |
| set-level: exact phone points to entity A, exact email to entity B | CRITICAL |

A critical conflict **always** blocks automatic MATCH → MANUAL_REVIEW.

## 12. Ranking and score gap

`matching/ranking.py` – sort by overall score (ties broken by entity ID for determinism), keep top 5.

```
Score Gap = best score − second-best score   (second = 0 if only one candidate)
```

A small gap means two master records look equally likely → ambiguous.

## 13. Confidence

`matching/decision_engine.py: confidence_score` – a point system independent of the raw score:

| Factor | Points |
|---|---|
| Overall similarity ≥ 90 / ≥ 80 / ≥ 65 | 30 / 20 / 10 |
| Strongly matching fields (≥ 90) | +8 each, max 32 |
| Critical identifier agreement (phone or email exact, or strong exact rule) | +15 |
| Score gap ≥ 10 / ≥ 5 | 15 / 8 |
| Data completeness | up to 8 |
| Conflicts | −30 per critical, −10 per warning |

HIGH ≥ 70 · MEDIUM ≥ 45 · LOW otherwise. Example: score 95, no conflict, 4 strong fields, gap 12 → HIGH. Score 89, email conflict, gap 2 → LOW.

## 14. Decision rules

```
no candidate                                   → NO_MATCH
score ≥ 85 AND gap ≥ 5 AND no critical conflict → MATCH
score ≥ 85 BUT critical conflict OR gap < 5     → MANUAL_REVIEW
65 ≤ score < 85                                 → MANUAL_REVIEW
score < 65                                      → NO_MATCH
```

Thresholds (85 / 65 / 5) are **prototype settings, not regulatory requirements**, and live in the algorithm version. Every decision carries the rule that fired and a plain-language explanation.

## 15. Merge process

`matching/merge_engine.py` + Merge Review page. Nothing merges automatically. Master and incoming are shown field by field with a status (identical / format only / different / incoming fills blank). Default survivorship: keep master, fill blanks from incoming; the user can override per field. CONFIRM MERGE updates the master and stores old/new values; REJECT MERGE is recorded (and counts as a dispute); a confirmed merge can be REVERSED (restores master; counts as a dispute and a merge error).

## 16. Performance metrics

`performance/metrics.py`

| Metric | Formula | Needs labels? |
|---|---|---|
| Match Rate | MATCH / total | no |
| **HIT Rate** | records whose best candidate score ≥ manual-review threshold / total | no |
| Manual Review Rate | MANUAL_REVIEW / total | no |
| Precision | TP / (TP + FP) | yes |
| Recall | TP / (TP + FN) | yes |
| F1 | 2·P·R / (P + R) | yes |
| False Positive Rate | FP / (FP + TN) | yes |
| False Negative Rate | FN / (FN + TP) | yes |
| Accuracy | (TP + TN) / all | yes |
| Dispute Rate | disputed matches / total MATCH | from reviews |
| Merge Error Rate | incorrect merges / confirmed merges | from reviews / labels |
| Candidate reduction | 1 − candidates / master records | no |

Definitions: **TP** = MATCH to the correct entity; **FP** = MATCH but truth is NO_MATCH or a different entity; **FN** = truth is MATCH but predicted NO_MATCH; **TN** = NO_MATCH and truth NO_MATCH. MANUAL_REVIEW records are *deferred* decisions – excluded from the confusion matrix and reported via Manual Review Rate.

**HIT Rate vs Precision.** HIT Rate asks *did the search find an acceptable candidate?* Precision asks *of the automatic matches, how many were right?* When no labels exist the UI prints **"Ground truth unavailable — metric not calculated."**

Every run stores all of these in `performance_runs`; they are recomputed whenever labels are loaded or a human reviews/merges, so the history stays honest.

## 17. Ground truth

Labels (`incoming_id, true_entity_id, true_decision`) come from the generator, from human reviews (a confirmed decision becomes a label) or from an uploaded .xlsx/.csv. The Ground Truth page shows TP/TN/FP/FN, precision, recall, F1, FPR, FNR, accuracy, a confusion matrix and a per-record outcome table. It measures the matching algorithm only – it is not an AI validation framework.

## 18. Algorithm versioning

Weights, thresholds, blocking passes, rare-value switch and top-N form an **algorithm version** (v1.0, v1.1 …). Changing any of them creates a new version; versions are never overwritten. Every run records its version, so runs can be compared (Performance → Algorithm Comparison: Improvement / Degradation in percentage points) and trends can be coloured by version.

## 19. Regression and stability testing

* **Regression test** – runs the same golden dataset through two versions in memory and compares precision, recall, F1, FPR, FNR, HIT rate and manual review rate. A drop (or rise, for lower-is-better metrics) beyond the material threshold (default 2 pp) prints **"Potential regression detected."** Rule-based, no AI.
* **Stability test** – runs identical input N times; candidate, score and decision must be identical → **STABLE** (the engine is deterministic).

## 20. Dashboard

Sidebar navigation: 1 Executive Dashboard · 2 Search & Match · 3 Batch Upload · 4 Incoming Data Generator · 5 Master Data · 6 Match Results · 7 Manual Review · 8 Merge Review · 9 Performance · 10 Algorithm Versions · 11 Ground Truth · 12 Thresholds · 13 Audit Log · 14 Methodology.

Every page has a **"How does this work?"** expander. The home page shows KPI cards with Green/Amber/Red indicators, decision distribution, 9 trend charts, version comparison and an input-data-quality strip. Monitoring thresholds (prototype values, user-editable) live on the Thresholds page.

## 21. Installation

```bash
git clone <your-repo-url>
cd search-match-system
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10+ is required. No API keys, no external services.

## 22. Running locally

```bash
# optional: pre-load 5,000 master + 100 incoming records and run matching
python -m database.seed_database --master 5000 --incoming 100

streamlit run app.py
```

The database is created automatically in `storage/smm.db`. Set `SMM_DB_PATH` to use a different file.

## 23. Tests

```bash
pytest
```

73 tests cover normalization, blocking, exact and fuzzy matching, weighted scoring and missing values, rare-value weighting, conflict detection, ranking and score gap, the decision engine, confidence, precision/recall/F1/FPR/FNR, HIT/dispute/merge-error rates, RAG thresholds, data generation, validation, regression testing, stability testing and the end-to-end database workflow.

## 24. GitHub setup

```bash
cd search-match-system
git init
git add .
git commit -m "Phase 1: Search, Match & Merge engine with performance monitoring"
git branch -M main
git remote add origin https://github.com/<your-username>/search-match-system.git
git push -u origin main
```

`.gitignore` excludes the SQLite database, generated datasets, secrets, caches and temporary files.

## 25. Deployment

```
GitHub Repository  →  Streamlit Community Cloud (connected to GitHub)  →  Interactive Dashboard
```

1. Push the repository to GitHub.
2. Sign in to [share.streamlit.io](https://share.streamlit.io) with GitHub, click **New app**, select the repo, branch `main`, main file `app.py`.
3. Deploy. Requirements are installed from `requirements.txt`; the app creates its SQLite database on first start (generate data from the UI or add a startup call to the seed script).

Notes: Streamlit Community Cloud storage is ephemeral – generated data is lost on restart (fine for a demo). **GitHub Pages cannot run a Streamlit (Python) application**; it only serves static files.

## 26. Demo walkthrough

1. **Executive Dashboard** – overview.
2. **Master Data** → 5,000 records → GENERATE MASTER DATA.
3. **Incoming Data Generator** → 100 records, 70/15/5/5/5 → GENERATE (matching runs immediately). Expect roughly 75 MATCH · 10 MANUAL_REVIEW · 15 NO_MATCH.
4. **Match Results** → filter Decision = MATCH → open a record → candidate, field scores, overall score, blocking passes, confidence, score gap, decision explanation.
5. Filter scenario **S9** → two candidates both at 100, gap 0 → MANUAL_REVIEW. Filter **S8** → phone 100 vs email ≈ 20 → critical conflict.
6. Filter Decision = NO_MATCH → best candidate below 65 or no candidate.
7. **Search & Match** → Load worked example → MATCH C01023, 5,000 → 11 candidates (99.78 % reduction).
8. **Batch Upload** → download template, upload → results for every row → DOWNLOAD RESULTS.
9. **Ground Truth** → TP/FP/FN/TN, precision, recall, F1, FPR, FNR, confusion matrix.
10. **Manual Review** → confirm/reject a record; **Merge Review** → field-by-field diff → CONFIRM MERGE.
11. **Algorithm Versions** → change weights/thresholds → CREATE VERSION v1.1.
12. **Match Results** → re-run the same batch with v1.1. **Performance → Algorithm Comparison** → v1.0 vs v1.1, Improvement / Degradation. **Regression Test** → verdict. **Stability Test** → STABLE.
13. **Executive Dashboard** → trends now show both versions.

## 27. Limitations

* Prototype thresholds and weights are illustrative, not tuned on real data.
* SQLite and an in-memory index are fine for tens of thousands of records, not millions.
* Blocking can miss a true match when the incoming record has no phone/email **and** a misspelled surname in a different city (inherent trade-off of blocking; the phonetic pass mitigates spelling).
* Synthetic data is cleaner than real-world data; real feeds have more nulls, encoding issues and multilingual names.
* Single-user demo app – no authentication; "reviewer" names are free text.

## 28. Future improvements

* Phase 2: agentic monitoring & validation framework consuming `performance_runs`, thresholds and audit logs.
* Learned weights from labelled data (keeping the explainable linear structure).
* Additional blocking keys (DOB year + surname, email username), q-gram indexing.
* Transliteration / Indic-script name handling; nickname dictionaries.
* PostgreSQL backend and multi-user review queues with assignment.
* Sampling plans for periodic human validation.

## 29. Glossary

* **Entity resolution** – deciding whether two records refer to the same real-world person.
* **Blocking** – cheap pre-filter that limits detailed comparison to records sharing a key.
* **Fuzzy matching** – similarity between strings that are not identical (typos, order).
* **Jaro-Winkler** – string similarity that rewards matching prefixes; good for names.
* **Token Set / Token Sort Ratio** – similarity after splitting into words and ignoring order / repeated words.
* **Soundex** – phonetic code; words that sound alike get the same code.
* **Weighted score** – average of field scores where important fields count more.
* **Score gap** – best minus second-best score; small gap = ambiguous.
* **Ground truth** – labelled correct answers used to measure accuracy.
* **Precision / Recall** – correctness of matches made / completeness of matches found.
* **HIT rate** – share of records where the search found an acceptable candidate.
* **Dispute** – a human disagrees with an automatic match.
* **Regression** – a new version performs worse than the previous one on the same data.
