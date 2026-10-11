from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_db import XingDbMenuService
from krx_research.infrastructure.xing_db import PostgreSQLXingMenuRepository
from krx_research.infrastructure.xing_db.adaptive_raw_bridge import AdaptiveRawTrBridge, DataProviderUnavailableError


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V40 LS Xing DLL -> PostgreSQL 메뉴 통합 실행기")
    p.add_argument("--menu", type=int, choices=(2, 5, 7), required=True)
    p.add_argument("--start", type=_date)
    p.add_argument("--end", type=_date)
    p.add_argument("--ticker")
    p.add_argument("--max-tickers", type=int, default=0)
    p.add_argument("--chunk-days", type=int, default=90)
    p.add_argument("--venues", default="NXT,COMBINED")
    p.add_argument("--force-refresh", action="store_true")
    p.add_argument("--no-investor", action="store_true",
                   help="메뉴 7 진단용: t8451만 실행하고 t1702는 별도 메뉴 5에서 검증")
    p.add_argument("--verification-marker", action="store_true")
    p.add_argument("--allow-today-before-close", action="store_true",
                   help="진단용. 일반 실행에서는 사용하지 마십시오.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    today = dt.date.today()
    end = args.end or today
    start = args.start or (end - dt.timedelta(days=7 if args.menu in (5, 7) else 0))

    bridge = AdaptiveRawTrBridge(ROOT, progress=lambda m: print(m, flush=True))
    repository = PostgreSQLXingMenuRepository(application_name=f"xing_menu_{args.menu}_v41_3")
    try:
        with XingDbMenuService(bridge, repository) as service:
            if args.menu == 2:
                report = service.run_menu2(
                    as_of=end, progress=lambda m: print(m, flush=True),
                    enforce_cutoff=not args.allow_today_before_close,
                )
            elif args.menu == 5:
                report = service.run_menu5(
                    start=start, end=end, ticker=args.ticker, max_tickers=args.max_tickers,
                    chunk_days=args.chunk_days, progress=lambda m: print(m, flush=True),
                    force_refresh=args.force_refresh,
                )
            else:
                venues = tuple(v.strip().upper() for v in args.venues.split(",") if v.strip())
                report = service.run_menu7(
                    start=start, end=end, ticker=args.ticker, max_tickers=args.max_tickers,
                    venues=venues, progress=lambda m: print(m, flush=True),
                    enforce_cutoff=not args.allow_today_before_close,
                    force_refresh=args.force_refresh, include_investor=not args.no_investor,
                )
    except DataProviderUnavailableError as exc:
        print(f"[FAIL] {exc}", flush=True); return 3

    for stage in report.stages:
        if not stage.passed:
            state = "FAIL"
        elif stage.message.startswith("SKIP"):
            state = "SKIP"
        else:
            state = "PASS"
        print(f"[{state}] {stage.name}: {stage.affected_rows:,}건 {stage.message}", flush=True)
    print(
        f"MENU {int(report.action)} {'COMPLETE' if report.passed else 'INCOMPLETE'} / "
        f"총 {report.affected_rows:,}건",
        flush=True,
    )
    if args.verification_marker:
        print(f"V41_AFFECTED_ROWS={report.affected_rows}", flush=True)
    return 0 if report.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
