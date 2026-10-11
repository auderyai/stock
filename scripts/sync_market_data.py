"""Fetch login-free KRX data and persist it to the configured database."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from krx_research.archive import ArchiveLayout
from krx_research.collectors import (
    OhlcvCoverageError,
    effective_history_start,
    fetch_ohlcv,
    normalize_ticker,
    require_ohlcv_coverage,
)
from krx_research.database import open_research_store, resolve_database_target
from krx_research.pipelines import refresh_security_master

KST = ZoneInfo("Asia/Seoul")


def parse_args() -> argparse.Namespace:
    today = dt.datetime.now(tz=KST).date()
    parser = argparse.ArgumentParser(
        description="Fetch login-free KRX data and upsert it into the configured database."
    )
    parser.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        help="Six-digit ticker; repeat the option for multiple tickers.",
    )
    parser.add_argument("--start", default=(today - dt.timedelta(days=35)).isoformat())
    parser.add_argument("--end", default=today.isoformat())
    parser.add_argument(
        "--skip-security-master",
        action="store_true",
        help="Skip the FinanceDataReader KRX security-master refresh.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    layout = ArchiveLayout(project_root)
    layout.ensure()
    database_target = resolve_database_target(project_root)
    tickers = args.tickers or ["005930"]

    security_rows = 0
    filtered_codes: dict[str, int] = {}
    ticker_results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    with open_research_store(database_target) as store:
        security_master = refresh_security_master(
            store,
            skip=args.skip_security_master,
        )
        security_rows = int(security_master["rows_written"])
        filtered_codes = {
            source: len(codes)
            for source, codes in dict(
                security_master.get("filtered_invalid_ticker_codes", {})
            ).items()
        }

        for ticker in tickers:
            try:
                code = normalize_ticker(ticker)
                listing_date = (store.get_security(code) or {}).get("listing_date")
                fetch_start = effective_history_start(args.start, listing_date)
                ohlcv = fetch_ohlcv(code, fetch_start, args.end)
                coverage = require_ohlcv_coverage(
                    ohlcv,
                    args.start,
                    args.end,
                    listing_date=listing_date,
                    source_history_start=ohlcv.attrs.get("source_history_start"),
                    allow_source_limit=True,
                )
                written = store.upsert_ohlcv(ohlcv)
                ticker_results.append({
                    "ticker": code,
                    "rows_written": written,
                    "source": ohlcv.attrs.get("source"),
                    "fallback_used": bool(ohlcv.attrs.get("fallback_used", False)),
                    "coverage": coverage,
                    "quality": ohlcv.attrs.get("quality_summary", {}),
                    "adjusted_overlap_rows": ohlcv.attrs.get("adjusted_overlap_rows"),
                    "provider_attempts": ohlcv.attrs.get("provider_attempts", []),
                    "source_history_limited": coverage["status"] == "source_limited",
                })
            except Exception as error:  # noqa: BLE001
                failure = {"ticker": str(ticker), "error": f"{type(error).__name__}: {error}"}
                if isinstance(error, OhlcvCoverageError):
                    failure["coverage"] = error.coverage
                failures.append(failure)
        summary = store.summary()

    result = {
        **summary,
        "security_rows_written": security_rows,
        "security_master": security_master,
        "filtered_invalid_ticker_count": filtered_codes,
        "tickers": ticker_results,
        "failures": failures,
        "status": "failed" if failures else "completed",
        "krx_login_used": False,
    }
    timestamp = dt.datetime.now(tz=KST).strftime("%Y%m%d_%H%M%S_%f")
    log_path = layout.log_root / f"market_sync_{timestamp}.json"
    result["log_path"] = str(log_path)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    log_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["quick_check"] == "ok" and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
