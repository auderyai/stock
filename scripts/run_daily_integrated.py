"""Daily orchestrator. --ls-supplement is Menu 7 and is backed by V40 OOP service."""
from __future__ import annotations
import argparse, datetime as dt, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def alert(message):
    print(message,flush=True)
    if os.name=="nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,message,"KRX 당일 갱신 결과",0x40)
        except Exception: pass

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--ls-supplement",action="store_true")
    p.add_argument("--quick-combined",action="store_true")
    p.add_argument("--report-pages",type=int,default=5)
    p.add_argument("--ticker")
    p.add_argument("--start",type=dt.date.fromisoformat)
    p.add_argument("--end",type=dt.date.fromisoformat,default=dt.date.today())
    args=p.parse_args(argv)
    if args.end >= dt.date.today() and dt.datetime.now().time() < dt.time(20,10):
        print("당일 확정 DB 갱신은 20:10 이후에만 실행할 수 있습니다.",file=sys.stderr,flush=True)
        return 4
    if args.ls_supplement:
        start=args.start or (args.end-dt.timedelta(days=7))
        command=["run_xing_db_menu.py","--menu","7","--start",start.isoformat(),"--end",args.end.isoformat(),
                 "--venues","COMBINED" if args.quick_combined else "NXT,COMBINED"]
        if args.ticker: command += ["--ticker",args.ticker]
        stages=[("LS 종목별 일봉·수급 원본 보완",command)]
    else:
        stages=[("시장별 일봉 (2번 방식)",["run_daily_pipeline.py"]),
                ("LS 수급 원본 최근 4일",["update_ls_investor_raw.py","--recent-days","4","--chunk-days","4"]),
                ("네이버 최신 리서치",["update_naver_research.py","--pages","1"])]
    started=time.monotonic(); results=[]
    for name,cmd in stages:
        path=ROOT/"scripts"/cmd[0]
        if not path.is_file(): results.append((name,2)); continue
        print(f"[{name}] 시작",flush=True)
        r=subprocess.run([sys.executable,str(path),*cmd[1:]],cwd=ROOT,check=False)
        results.append((name,r.returncode))
        print(f"[{name}] {'완료' if r.returncode==0 else '부분 저장' if r.returncode==3 else '미완료'}",flush=True)
    msg=f"{dt.datetime.now():%Y-%m-%d %H:%M} 갱신: "+", ".join(f"{n} {'완료' if rc==0 else '미완료'}" for n,rc in results)+f" / {int(time.monotonic()-started)}초"
    alert(msg)
    return 0 if all(rc==0 for _,rc in results) else 2
if __name__=="__main__": raise SystemExit(main())
