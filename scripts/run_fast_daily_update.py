"""Menu 2 convenience entry. Canonical work is delegated to the V40 daily wrapper."""
from __future__ import annotations
import subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    began=time.monotonic()
    r=subprocess.run([
        sys.executable,str(ROOT/'scripts'/'run_daily_pipeline.py'),
        '--until-complete','--no-investor','--markets','KOSPI','KOSDAQ'
    ],cwd=ROOT,check=False)
    print(f"메뉴 2 종료: {int(time.monotonic()-began)}초 / {'완료' if r.returncode==0 else '미완료'}",flush=True)
    return r.returncode
if __name__=='__main__': raise SystemExit(main())
