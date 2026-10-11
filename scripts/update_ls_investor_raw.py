"""Backward-compatible t1702 raw updater using the V40 Menu 5 service."""
from __future__ import annotations
import argparse, datetime as dt, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from krx_research.application.xing_db import XingDbMenuService
from krx_research.collectors.xing.bridge import XingBridgeClient
from krx_research.infrastructure.xing_db import PostgreSQLXingMenuRepository

def main(argv=None):
    p=argparse.ArgumentParser(description="LS t1702 원본 수급 적재 V40")
    p.add_argument("--ticker")
    p.add_argument("--start",type=dt.date.fromisoformat)
    p.add_argument("--end",type=dt.date.fromisoformat,default=dt.date.today())
    p.add_argument("--recent-days",type=int,default=0)
    p.add_argument("--max-tickers",type=int,default=0)
    p.add_argument("--chunk-days",type=int,default=90)
    p.add_argument("--empty-stop-chunks",type=int,default=6)
    p.add_argument("--progress-every",type=int,default=12)    # legacy-compatible; service reports per stock
    args=p.parse_args(argv)
    start=args.start or (args.end-dt.timedelta(days=max(0,args.recent_days-1)) if args.recent_days else dt.date(1980,1,1))
    with XingDbMenuService(XingBridgeClient(ROOT),PostgreSQLXingMenuRepository(application_name="t1702_raw_v40")) as svc:
        report=svc.run_menu5(start=start,end=args.end,ticker=args.ticker,max_tickers=args.max_tickers,
                             chunk_days=args.chunk_days,empty_stop_chunks=args.empty_stop_chunks,
                             progress=lambda m:print(m,flush=True))
    return 0 if report.passed else 3
if __name__=="__main__": raise SystemExit(main())
