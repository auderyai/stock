"""Collect a bounded, resumable batch of login-free adjusted OHLCV history."""

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
from krx_research.pipelines import sync_ohlcv_history


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist adjusted Naver OHLCV for a bounded KRX ticker batch."
    )
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument(
        "--all",
        action="store_true",
        help="Use tickers from the local security_master table.",
    )
    universe.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        help="Six-digit ticker; repeat for multiple tickers.",
    )
    parser.add_argument("--market", choices=["ALL", "KOSPI", "KOSDAQ", "KONEX"], default="ALL")
    parser.add_argument("--start", required=True, help="First history date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, help="Last history date (YYYY-MM-DD).")
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=10,
        help="Maximum missing tickers processed in this run (default: 10).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        choices=range(1, 9),
        help="Concurrent network workers from 1 to 8 (default: 8).",
    )
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=3,
        help="Provider attempts per ticker (default: 3).",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Base seconds between retries (default: 2.0).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.0,
        help="Seconds between task submissions (default: 0).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch tickers whose prior attempt already covers the range.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    layout = ArchiveLayout(project_root)
    layout.ensure()
    database_target = resolve_database_target(project_root)
    label = database_label(database_target)
    with open_research_store(database_target, read_only=False) as store:
        tickers = store.list_security_tickers(args.market) if args.all else args.tickers
        if not tickers:
            result = {
                "database_path": label,
                "status": "failed",
                "error": "No tickers were found. Refresh security_master first.",
                "krx_login_used": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        result = sync_ohlcv_history(
            store,
            tickers,
            args.start,
            args.end,
            force=args.force,
            max_tickers=args.max_tickers,
            workers=args.workers,
            retry_attempts=args.retry_attempts,
            retry_delay=args.retry_delay,
            request_delay=args.request_delay,
        )

    print(
        json.dumps(
            {"database_path": label, **result},
            ensure_ascii=False,
            indent=2,
        )
    )
    if result["quick_check"] != "ok":
        return 3
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
