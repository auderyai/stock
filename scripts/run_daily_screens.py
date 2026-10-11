"""Generate the four daily screen outputs from configured indicators."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from krx_research.analytics import (
    EMA_DEFAULT_GAP_TOLERANCE,
    EMA_DEFAULT_MIN_SIMILARITY,
    EMA_GAP_TOLERANCE_OPTIONS,
)
from krx_research.archive import ArchiveLayout
from krx_research.database import (
    database_label,
    open_research_store,
    resolve_database_target,
)
from krx_research.pipelines import run_daily_screens


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank EMA similarity, 52-week highs, Bollinger breakouts, and returns."
    )
    parser.add_argument(
        "--as-of",
        help="Use the latest indicator date on or before YYYY-MM-DD (default: latest).",
    )
    parser.add_argument(
        "--comparison-ticker",
        default="222800",
        help="EMA pattern reference ticker (default: 222800).",
    )
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument(
        "--ema-min-similarity",
        type=float,
        default=EMA_DEFAULT_MIN_SIMILARITY,
        help="Minimum 36-pair EMA order similarity percentage (default: 85).",
    )
    parser.add_argument(
        "--ema-gap-tolerance",
        type=float,
        choices=EMA_GAP_TOLERANCE_OPTIONS,
        default=EMA_DEFAULT_GAP_TOLERANCE,
        help="Maximum 28-pair EMA gap difference in percentage points (1-4; default: 2).",
    )
    parser.add_argument("--output-directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    layout = ArchiveLayout(project_root)
    layout.ensure()
    database_target = resolve_database_target(project_root)
    with open_research_store(database_target) as store:
        resolved_date = store.latest_technical_indicator_date(args.as_of)
        if resolved_date is None:
            result = {
                "database_path": database_label(database_target),
                "status": "failed",
                "error": "No technical indicators are available for screening.",
                "network_used": False,
                "krx_login_used": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        output_directory = args.output_directory or layout.daily_screen_root(resolved_date)
        try:
            result = run_daily_screens(
                store,
                output_directory=output_directory,
                as_of_date=args.as_of,
                comparison_ticker=args.comparison_ticker,
                top_n=args.top_n,
                ema_min_similarity=args.ema_min_similarity,
                ema_gap_tolerance=args.ema_gap_tolerance,
            )
        except ValueError as error:
            result = {
                "status": "failed",
                "error": str(error),
                "network_used": False,
                "krx_login_used": False,
            }

    payload = {"database_path": database_label(database_target), **result}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result["status"] != "completed":
        return 2
    return 0 if result["quick_check"] == "ok" else 3


if __name__ == "__main__":
    raise SystemExit(main())
