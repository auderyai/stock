from __future__ import annotations
import datetime as dt
import os, sys
from pathlib import Path
ROOT=Path(os.environ.get('NEW_STOCK_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/'src'))
from krx_research.application.xing_db.service import XingDbMenuService
DAY=dt.date(2026,10,2)
class Bridge:
    def __init__(self): self.calls=[]
    def connect(self): pass
    def close(self): pass
    def raw_tr(self,tr,values):
        self.calls.append((tr,dict(values)))
        if tr=='t8424': return {'rows':[{'upcode':'101','hname':'코스피200'},{'upcode':'301','hname':'코스닥150'},{'upcode':'001','hname':'종합'}]}
        if tr=='t8436': return {'rows':[{'shcode':'005930','hname':'삼성전자'}]}
        if tr=='t1516':
            n=201 if values['upcode']=='101' else 150
            return {'rows':[{'shcode':f'{i:06d}'} for i in range(1,n+1)]}
        if tr=='t8429': return {'rows':[{'date':'20261002','close':'101'}]}
        raise AssertionError(tr)
class Repo:
    def initialize(self): pass
    def close(self): pass
    def latest_market_date(self): return DAY
    def upsert_sector_master(self,rows): return len(rows)
    def upsert_security_master(self,rows): return len(rows)
    def replace_index_membership(self,*args): return len(args[-1])
    def upsert_sector_daily(self,code,rows): return len(rows)
progress=[]
svc=XingDbMenuService(Bridge(),Repo())
report=svc.run_menu2(as_of=DAY,enforce_cutoff=False,progress=progress.append)
assert report.passed
starts=[x for x in progress if '조회 시작' in x and x.startswith('[t8429 ')]
dones=[x for x in progress if '완료 |' in x and x.startswith('[t8429 ')]
assert len(starts)==3, progress
assert len(dones)==3, progress
assert any('ETA 계산 중' in x for x in starts), progress
assert any('t8429 업종 일봉 3건 저장 완료' in x for x in progress), progress
print('V41_6_PROGRESS_UNIT_CHECK: PASS')
