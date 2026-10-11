from __future__ import annotations
import ast, datetime as dt
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    from krx_research.application.xing_db.policy import DailyCloseWritePolicy
    sunday=dt.datetime(2026,10,5,16,30)
    latest=dt.date(2026,10,2)
    assert DailyCloseWritePolicy.resolve_end_date(dt.date(2026,10,5),latest,now=sunday)==latest
    assert DailyCloseWritePolicy.resolve_end_date(dt.date(2027,10,7),dt.date(2026,10,5),now=sunday)==dt.date(2026,10,4)
    repo=(ROOT/'src/krx_research/infrastructure/xing_db/postgresql_repository.py').read_text(encoding='utf-8')
    assert 'WHERE stock_name=%s' in repo
    window=(ROOT/'src/krx_research/qt/job_menu/window.py').read_text(encoding='utf-8')
    assert '6자리 종목코드 또는 정확한 종목명' in window
    for rel in ['src/krx_research/application/xing_db/service.py','src/krx_research/application/xing_db/policy.py','src/krx_research/infrastructure/xing_db/postgresql_repository.py','src/krx_research/qt/job_menu/window.py']:
        ast.parse((ROOT/rel).read_text(encoding='utf-8'),filename=rel)
    print('V42_3_GUI_SMOKE_FIX_CHECK: PASS')
    return 0
if __name__=='__main__': raise SystemExit(main())
