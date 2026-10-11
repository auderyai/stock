"""Backward-compatible t8451 venue updater using the V40 Menu 7 application service."""
from __future__ import annotations
import argparse, datetime as dt, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from krx_research.application.xing_db import XingDbMenuService
from krx_research.collectors.xing.bridge import XingBridgeClient
from krx_research.infrastructure.xing_db import PostgreSQLXingMenuRepository
NXT_START=dt.date(2025,3,4)

def main(argv=None):
    p=argparse.ArgumentParser(description="LS t8451 NXT/통합 일봉 증분 갱신 V40")
    p.add_argument("--ticker")
    p.add_argument("--venue",choices=("NXT","COMBINED","BOTH"),default="BOTH")
    p.add_argument("--start",type=dt.date.fromisoformat,default=NXT_START)
    p.add_argument("--end",type=dt.date.fromisoformat,default=dt.date.today())
    p.add_argument("--delay",type=float,default=.08)  # backward compatibility; bridge owns delay
    p.add_argument("--allow-today-before-close",action="store_true")
    args=p.parse_args(argv)
    venues=("NXT","COMBINED") if args.venue=="BOTH" else (args.venue,)
    with XingDbMenuService(XingBridgeClient(ROOT,delay=args.delay),PostgreSQLXingMenuRepository(application_name="menu7_venue_v40")) as svc:
        report=svc.run_menu7(start=args.start,end=args.end,ticker=args.ticker,venues=venues,
                             progress=lambda m:print(m,flush=True),
                             enforce_cutoff=not args.allow_today_before_close, include_investor=False)
    return 0 if report.passed else 3
if __name__=="__main__": raise SystemExit(main())
