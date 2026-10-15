from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_db import XingDbMenuService
from krx_research.infrastructure.xing_db import PostgreSQLXingCloudRepository
from krx_research.infrastructure.xing_db.adaptive_raw_bridge import (
    AdaptiveRawTrBridge,
    DataProviderUnavailableError,
)


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="클라우드 LS 데이터 단계 실행기")
    result.add_argument("--stage", type=int, choices=(5, 7), required=True)
    result.add_argument("--start", type=_date, required=True)
    result.add_argument("--end", type=_date, required=True)
    result.add_argument("--max-tickers", type=int, default=0)
    result.add_argument("--ticker-offset", type=int, default=0)
    result.add_argument("--chunk-days", type=int, default=1)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    bridge = AdaptiveRawTrBridge(ROOT, progress=lambda message: print(message, flush=True))
    repository = PostgreSQLXingCloudRepository(application_name=f"cloud_stage_{args.stage}")
    try:
        with XingDbMenuService(bridge, repository) as service:
            if args.stage == 5:
                report = service.run_menu5(
                    start=args.start,
                    end=args.end,
                    max_tickers=args.max_tickers,
                    ticker_offset=args.ticker_offset,
                    chunk_days=args.chunk_days,
                    progress=lambda message: print(message, flush=True),
                    independent_target=True,
                )
                if report.metadata.get("code_count") == "0":
                    print("[COMPLETE] 더 처리할 종목이 없습니다.", flush=True)
                    return 4
            else:
                report = service.run_menu7(
                    start=args.start,
                    end=args.end,
                    venues=("NXT", "COMBINED"),
                    progress=lambda message: print(message, flush=True),
                    include_investor=False,
                    independent_target=True,
                )
    except DataProviderUnavailableError as exc:
        print(f"[FAIL] {exc}", flush=True)
        return 3

    for stage in report.stages:
        state = "PASS" if stage.passed else "FAIL"
        print(f"[{state}] {stage.name}: {stage.affected_rows:,}건 {stage.message}", flush=True)
    return 0 if report.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
