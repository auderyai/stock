"""V40 Menu-2 wrapper around the preserved pre-V40 daily pipeline.

The installer saves the existing implementation as run_daily_pipeline_v39_core.py.
This wrapper never reimplements the KRX pipeline; it adds the LS DB stage only after
that preserved core exits successfully.
"""
from __future__ import annotations
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'scripts'/'run_daily_pipeline_v39_core.py'
sys.path.insert(0,str(ROOT/'src'))

from krx_research.collectors.xing.worker_runtime import Xing32Environment


def _as_of(argv:list[str]) -> dt.date:
    for i,arg in enumerate(argv):
        if arg=='--as-of' and i+1<len(argv):
            return dt.date.fromisoformat(argv[i+1])
        if arg.startswith('--as-of='):
            return dt.date.fromisoformat(arg.split('=',1)[1])
    return dt.date.today()


def main(argv:list[str]|None=None) -> int:
    args=list(sys.argv[1:] if argv is None else argv)
    if not CORE.is_file():
        print(f'[ERROR] preserved daily pipeline not found: {CORE}',file=sys.stderr,flush=True)
        return 90
    day=_as_of(args)
    now=dt.datetime.now()
    if day>=now.date() and now.time()<dt.time(20,10):
        print('당일 확정 DB 갱신은 20:10 이후에만 실행할 수 있습니다.',file=sys.stderr,flush=True)
        return 4

    core=subprocess.run([sys.executable,str(CORE),*args],cwd=ROOT,check=False)
    if core.returncode:
        print(f'[V40] 기존 KRX pipeline 실패({core.returncode}); LS DB 단계는 실행하지 않습니다.',file=sys.stderr,flush=True)
        return core.returncode

    xing = Xing32Environment(ROOT).inspect()
    if not xing.available:
        print(
            '[V40] LS DB 단계 SKIP: KRX 일봉 갱신은 완료됐으나 '
            f'선택 기능인 32bit Xing Worker를 사용할 수 없습니다 ({xing.detail}).',
            flush=True,
        )
        return 0

    ls=subprocess.run([
        sys.executable,str(ROOT/'scripts'/'run_xing_db_menu.py'),
        '--menu','2','--end',day.isoformat(),
    ],cwd=ROOT,check=False)
    if ls.returncode:
        print(f'[V40] LS DB 통합 실패({ls.returncode})',file=sys.stderr,flush=True)
        return ls.returncode
    print('[V40] 메뉴 2 KRX + LS PostgreSQL 통합 완료',flush=True)
    return 0

if __name__=='__main__': raise SystemExit(main())
