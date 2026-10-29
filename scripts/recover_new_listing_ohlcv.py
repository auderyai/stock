from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.new_listing_recovery import NewListingRecoveryService
from krx_research.collectors import fetch_ohlcv, fetch_security_master
from krx_research.collectors.bounded_market_data import BoundedOhlcvFetcher
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.operational_repository import OperationalDataRepository

KST = ZoneInfo("Asia/Seoul")


def parse_args() -> argparse.Namespace:
    today = dt.datetime.now(KST).date()
    parser = argparse.ArgumentParser(description="신규 상장주 누락 일봉 일회성 복구")
    parser.add_argument("--since", default=f"{today.year}-01-01")
    parser.add_argument("--as-of")
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = DataEngineSettings.from_environment()
    with OperationalDataRepository(
        settings,
        "new_listing_ohlcv_recovery",
        read_only=not args.apply,
    ) as repository:
        as_of = args.as_of or repository.latest_ohlcv_date()
        if as_of is None:
            raise RuntimeError("PostgreSQL에 일봉 기준일이 없습니다.")
        master = fetch_security_master()
        if args.apply:
            repository.upsert_security_master(master)
        with BoundedOhlcvFetcher(fetch_ohlcv) as fetcher:
            report = NewListingRecoveryService(repository, fetcher).recover(
                master,
                args.since,
                as_of,
                tickers=tuple(args.ticker),
                max_tickers=args.max_tickers,
                apply=args.apply,
                progress=print,
            )
    stamp = dt.datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    log = ROOT / "logs" / f"new_listing_ohlcv_recovery_{stamp}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    report["log_path"] = str(log)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    log.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
