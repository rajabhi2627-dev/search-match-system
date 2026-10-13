"""Seed the database from the command line.

    python -m database.seed_database                 # 1,000 master + 100 incoming, run matching
    python -m database.seed_database --master 5000 --incoming 100
    python -m database.seed_database --master 500 --no-run
    python -m database.seed_database --febrl dataset1 --holdout 10   # FEBRL benchmark instead of synthetic data

Everything generated is synthetic (FEBRL datasets are published synthetic benchmarks).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# allow running as a script from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.database import get_session, init_db          # noqa: E402
from database import repository as repo                      # noqa: E402
from workflows.runner import generate_incoming_data, generate_master_data   # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the Search, Match & Merge database with synthetic data.")
    parser.add_argument("--master", type=int, default=1000, help="number of master records (default 1000)")
    parser.add_argument("--incoming", type=int, default=100, help="number of incoming records (default 100)")
    parser.add_argument("--match", type=float, default=70, help="expected match %% (default 70)")
    parser.add_argument("--no-match", dest="no_match", type=float, default=15, help="expected no-match %% (default 15)")
    parser.add_argument("--noisy", type=float, default=5, help="noisy records %% (default 5)")
    parser.add_argument("--ambiguous", type=float, default=5, help="ambiguous records %% (default 5)")
    parser.add_argument("--duplicate", type=float, default=5, help="duplicate records %% (default 5)")
    parser.add_argument("--seed", type=int, default=42, help="random seed")
    parser.add_argument("--no-run", action="store_true", help="do not run matching after generating")
    parser.add_argument("--febrl", choices=["dataset1", "dataset2", "dataset3", "dataset4"],
                        help="load a FEBRL benchmark dataset instead of generating synthetic data")
    parser.add_argument("--holdout", type=float, default=10, help="FEBRL: %% of originals held out of the master (default 10)")
    args = parser.parse_args(argv)

    init_db()
    with get_session() as session:
        repo.ensure_defaults(session)
        version = repo.get_active_version(session).version_name
    print(f"Database ready. Active algorithm version: {version}")

    if args.febrl:
        from workflows.runner import load_febrl_data
        s = load_febrl_data(args.febrl, holdout_pct=args.holdout, seed=args.seed, run_now=not args.no_run, actor="seed_script")
        print(f"FEBRL {s.dataset}: {s.master} master records, {s.incoming} incoming records in batch {s.batch_id} "
              f"({s.true_match} true matches, {s.true_no_match} true no-matches, {s.held_out} originals held out)")
        if s.run_id:
            with get_session() as session:
                run = repo.get_run(session, s.run_id)
                print(f"Matching run {run.run_id}: MATCH={run.total_matches} MANUAL_REVIEW={run.total_manual_reviews} "
                      f"NO_MATCH={run.total_no_matches} | precision={run.precision}% recall={run.recall}% F1={run.f1_score}%")
        print("Done. Start the app with:  streamlit run app.py")
        return 0

    m = generate_master_data(args.master, seed=args.seed, mode="replace", actor="seed_script")
    print(f"Master data: {m.inserted} synthetic records (worked example = {m.example_entity_id})")

    inc = generate_incoming_data(args.incoming, args.match, args.no_match, args.noisy, args.ambiguous, args.duplicate,
                                 seed=args.seed + 1, store_ground_truth=True, run_now=not args.no_run, actor="seed_script")
    print(f"Incoming data: batch {inc.batch_id} with {inc.records} records, {inc.ground_truth_labels} ground-truth labels")
    for scenario, count in sorted(inc.scenario_counts.items()):
        print(f"   {scenario:<40} {count}")
    if inc.run_id:
        with get_session() as session:
            run = repo.get_run(session, inc.run_id)
            print(f"Matching run {run.run_id}: MATCH={run.total_matches} MANUAL_REVIEW={run.total_manual_reviews} "
                  f"NO_MATCH={run.total_no_matches} | HIT rate={run.hit_rate}% precision={run.precision}% recall={run.recall}%")
    print("Done. Start the app with:  streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
