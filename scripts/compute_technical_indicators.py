"""Compute deterministic technical indicators from the local adjusted-price store."""

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
from krx_research.pipelines import sync_technical_indicators


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist EMA, 52-week-high, return, and Bollinger indicators."
    )
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument(
        "--all",
        action="store_true",
        help="Use every ticker with adjusted OHLCV in the local database.",
    )
    universe.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        help="Six-digit ticker; repeat for multiple tickers.",
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=50,
        help="Maximum stale tickers processed in this run (default: 50).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recalculate even when the stored input signature is unchanged.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, 13),
        default=8,
        help="Parallel CPU workers for calculation (default: 8).",
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
        tickers = store.list_ohlcv_tickers() if args.all else args.tickers
        if not tickers:
            result = {
                "database_path": label,
                "status": "failed",
                "error": "No adjusted OHLCV tickers were found. Run Phase 3 first.",
                "network_used": False,
                "krx_login_used": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        result = sync_technical_indicators(
            store,
            tickers,
            force=args.force,
            max_tickers=args.max_tickers,
            workers=args.workers,
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
