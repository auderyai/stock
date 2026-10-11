"""Export unresolved adjusted-history failures without a network request."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from krx_research.archive import ArchiveLayout
from krx_research.database import (
    database_label,
    open_research_store,
    resolve_database_target,
)
from krx_research.pipelines import audit_history_failures, write_history_failure_audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="Requested history start (YYYY-MM-DD).")
    parser.add_argument("--end", help="Requested history end (YYYY-MM-DD).")
    parser.add_argument(
        "--market",
        choices=["ALL", "KOSPI", "KOSDAQ", "KONEX"],
        default="ALL",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="Optional audit output directory; defaults to C:\\stock logs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if bool(args.start) != bool(args.end):
        raise SystemExit("--start and --end must be supplied together")

    project_root = Path(__file__).resolve().parents[1]
    layout = ArchiveLayout(project_root)
    layout.ensure()
    database_target = resolve_database_target(project_root)
    output_directory = args.output_directory or layout.log_root

    with open_research_store(database_target) as store:
        latest = store.latest_ohlcv_history_range()
        if args.start and args.end:
            start, end = args.start, args.end
            range_source = "command_line"
        elif latest is not None:
            start = latest["requested_start"]
            end = latest["requested_end"]
            range_source = "latest_finished_run"
        else:
            raise SystemExit(
                "No finished history run exists; supply --start and --end explicitly"
            )
        audit = audit_history_failures(store, start, end, market=args.market)
        quick_check = store.quick_check()

    paths = write_history_failure_audit(audit, output_directory)
    summary = {
        "status": audit["status"],
        "database_path": database_label(database_target),
        "range_source": range_source,
        "requested_start": audit["requested_start"],
        "requested_end": audit["requested_end"],
        "market": audit["market"],
        "unresolved_failure_count": audit["unresolved_failure_count"],
        "attempted_failure_rows": audit["attempted_failure_rows"],
        "category_counts": audit["category_counts"],
        "retryable_now_count": audit["retryable_now_count"],
        "retryable_now_tickers": audit["retryable_now_tickers"],
        "review_required_count": audit["review_required_count"],
        **paths,
        "quick_check": quick_check,
        "network_used": False,
        "krx_login_used": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if quick_check == "ok" else 3


if __name__ == "__main__":
    raise SystemExit(main())
