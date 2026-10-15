"""Backward-compatible Menu 5 entry point backed by V40 OOP application service."""
from __future__ import annotations
import argparse, datetime as dt, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from krx_research.application.xing_db import XingDbMenuService
from krx_research.infrastructure.xing_db import PostgreSQLXingMenuRepository
from krx_research.infrastructure.xing_db.adaptive_raw_bridge import AdaptiveRawTrBridge, DataProviderUnavailableError

def main(argv=None):
    p=argparse.ArgumentParser(description="메뉴 5: LS 수급 원본 날짜 범위 갱신")
    p.add_argument("--start",type=dt.date.fromisoformat,required=True)
    p.add_argument("--end",type=dt.date.fromisoformat,required=True)
    p.add_argument("--ticker")
    p.add_argument("--max-tickers",type=int,default=0)
    p.add_argument("--ticker-offset",type=int,default=0)
    p.add_argument("--empty-is-complete",action="store_true")
    p.add_argument("--chunk-days",type=int,default=90)
    p.add_argument("--empty-stop-chunks",type=int,default=0)
    p.add_argument("--force-refresh",action="store_true")
    p.add_argument("--independent-target",action="store_true")
    p.add_argument("--verification-marker",action="store_true")
    args=p.parse_args(argv)
    bridge=AdaptiveRawTrBridge(ROOT,progress=lambda m:print(m,flush=True))
    try:
        with XingDbMenuService(bridge,PostgreSQLXingMenuRepository(application_name="menu5_v41_3")) as svc:
            report=svc.run_menu5(start=args.start,end=args.end,ticker=args.ticker,max_tickers=args.max_tickers,
                                 ticker_offset=args.ticker_offset,
                                 chunk_days=args.chunk_days,empty_stop_chunks=args.empty_stop_chunks,
                                 progress=lambda m:print(m,flush=True),force_refresh=args.force_refresh,
                                 independent_target=args.independent_target)
    except DataProviderUnavailableError as exc:
        print(f"[FAIL] {exc}",flush=True); return 3
    if args.empty_is_complete and report.metadata.get("code_count") == "0":
        print("[COMPLETE] 더 처리할 종목이 없습니다.", flush=True)
        return 4
    for s in report.stages: print(f"{'PASS' if s.passed else 'FAIL'} {s.name}: {s.affected_rows:,}건 {s.message}")
    if args.verification_marker:
        print(f"V41_AFFECTED_ROWS={report.affected_rows}", flush=True)
    return 0 if report.passed else 3
if __name__=="__main__": raise SystemExit(main())
