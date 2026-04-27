"""Cron-style scheduled runner for the enrichment pipeline.

Wraps the main pipeline in a `schedule` loop so it can be triggered
on a recurring interval without an external cron daemon.

Usage:
    python scheduler.py --input data/sample_leads.csv --output results/enriched.csv --interval 60
"""

import argparse
import sys
import time
import traceback

import schedule

from main import process_leads


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the enrichment pipeline on a recurring schedule."
    )
    parser.add_argument("--input", required=True, help="Path to input CSV")
    parser.add_argument("--output", required=True, help="Path to output CSV")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Run interval in minutes (default: 60)",
    )
    return parser.parse_args()


def run_pipeline(input_path: str, output_path: str) -> None:
    """Single pipeline execution called by the scheduler.

    Wrapped in try/except so a single failed run (e.g. transient API outage)
    doesn't kill the scheduler — the next interval still fires.
    """
    print(f"[scheduler] Starting enrichment run: {input_path} → {output_path}")
    try:
        process_leads(input_path, output_path)
        print("[scheduler] Run complete.")
    except Exception as exc:
        print(f"[scheduler] Run FAILED: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("[scheduler] Continuing — next run will fire on schedule.", file=sys.stderr)


def main() -> None:
    args = parse_args()

    # Run once immediately, then on the interval
    run_pipeline(args.input, args.output)

    schedule.every(args.interval).minutes.do(
        run_pipeline, input_path=args.input, output_path=args.output
    )

    print(f"[scheduler] Scheduled every {args.interval} minute(s). Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
