"""Repair reviewed OHLCV failures without relaxing the normal data pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from krx_research.archive import ArchiveLayout
from krx_research.collectors import (
    fetch_ohlcv_for_recovery,
    normalize_ticker,
)
from krx_research.database import (
    PostgreSQLSettings,
    database_label,
    open_research_store,
    resolve_database_target,
)
from krx_research.pipelines import (
    audit_history_failures,
    refresh_security_master,
    sync_ohlcv_history,
)

KST = ZoneInfo("Asia/Seoul")
RECOVERY_CATEGORIES = {
    "adjusted_bounds_review",
    "invalid_trading_price",
    "incomplete_history",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument(
        "--all-failures",
        action="store_true",
        help="Use only unresolved failures in the requested range.",
    )
    universe.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        help="Reviewed six-digit failure ticker; repeat for multiple tickers.",
    )
    parser.add_argument("--start", required=True, help="First history date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, help="Last history date (YYYY-MM-DD).")
    parser.add_argument(
        "--market",
        choices=["ALL", "KOSPI", "KOSDAQ", "KONEX"],
        default="ALL",
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=10,
        help="Maximum reviewed failures processed in one run (default: 10).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        choices=range(1, 5),
        help="Concurrent network workers from 1 to 4 (default: 1).",
    )
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--request-delay", type=float, default=0.5)
    parser.add_argument(
        "--skip-security-master",
        action="store_true",
        help="Do not refresh public FDR listing dates before recovery.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    layout = ArchiveLayout(project_root)
    layout.ensure()
    database_target = resolve_database_target(project_root)
    label = database_label(database_target)

    stamp = dt.datetime.now(tz=KST).strftime("%Y%m%d_%H%M%S_%f")
    backup_suffix = ".dump"
    backup_path = layout.backup_root / f"krx_research_before_repair_{stamp}{backup_suffix}"
    log_path = layout.log_root / f"history_repair_{stamp}.json"
    security_rows = 0
    security_refresh: dict[str, object] | None = None

    with open_research_store(database_target) as store:
        audit = audit_history_failures(
            store,
            args.start,
            args.end,
            market=args.market,
        )
        eligible = {
            str(record["ticker"]): record
            for record in audit["records"]
            if record["category"] in RECOVERY_CATEGORIES
        }
        if args.all_failures:
            tickers = sorted(eligible)
        else:
            tickers = sorted({normalize_ticker(ticker) for ticker in args.tickers})
            not_reviewed = [ticker for ticker in tickers if ticker not in eligible]
            if not_reviewed:
                result = {
                    "status": "refused",
                    "database_path": label,
                    "error": "Explicit recovery is limited to unresolved reviewed failures.",
                    "not_reviewed_tickers": not_reviewed,
                    "network_used": False,
                    "krx_login_used": False,
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 2
        if not tickers:
            result = {
                "status": "clean",
                "database_path": label,
                "message": "No eligible unresolved history failures remain.",
                "network_used": False,
                "krx_login_used": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        from krx_research.database.backup import pg_dump_backup
        backup = pg_dump_backup(database_target, backup_path)
        selected_count = min(len(tickers), args.max_tickers)
        print(
            f"[history-repair] start selected={selected_count} "
            f"workers={args.workers}",
            file=sys.stderr,
            flush=True,
        )
        security_refresh = refresh_security_master(
            store,
            skip=args.skip_security_master,
        )
        security_rows = int(security_refresh["rows_written"])

        result = sync_ohlcv_history(
            store,
            tickers,
            args.start,
            args.end,
            fetcher=fetch_ohlcv_for_recovery,
            force=True,
            max_tickers=args.max_tickers,
            workers=args.workers,
            retry_attempts=args.retry_attempts,
            retry_delay=args.retry_delay,
            request_delay=args.request_delay,
            allow_quality_limit=True,
            progress=lambda event: print(
                f"[history-repair] {event['completed']}/{event['total']} "
                f"ticker={event['ticker']} status={event['status']} "
                f"rows={event['rows_written']}",
                file=sys.stderr,
                flush=True,
            ),
        )

    document = {
        "database_path": label,
        "backup_path": str(backup),
        "recovery_mode": True,
        "normal_pipeline_policy_changed": False,
        "eligible_failure_count": len(eligible),
        "eligible_categories": sorted(RECOVERY_CATEGORIES),
        "security_master_rows_written": security_rows,
        "security_master": security_refresh,
        "security_master_refresh_error": (
            None if security_refresh is None else security_refresh["warning"]
        ),
        **result,
        "log_path": str(log_path),
        "krx_login_used": False,
    }
    rendered = json.dumps(document, ensure_ascii=False, indent=2)
    log_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if result["quick_check"] != "ok":
        return 3
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
