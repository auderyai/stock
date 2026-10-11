from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from krx_research.application.xing_db.service import XingDbMenuService


class FakeBridge:
    def __init__(self): self.connected=False; self.calls=[]
    def connect(self): self.connected=True
    def close(self): self.connected=False
    def raw_tr(self,tr,values):
        self.calls.append((tr,dict(values)))
        if tr=='t8424':
            return {'rows':[{'hname':'코스피200','upcode':'101'},{'hname':'코스닥150','upcode':'301'}]}
        if tr=='t8436':
            return {'rows':[{'hname':'삼성전자','shcode':'005930'},{'hname':'테스트스팩','shcode':'999999'}]}
        if tr=='t1516':
            count=200 if values.get('upcode')=='101' else 150
            return {'rows':[{'hname':f'종목{i:03d}','shcode':f'{i:06d}'} for i in range(1,count+1)] + [{'hname':'HEADER','shcode':''}]}
        if tr=='t8429':
            return {'rows':[{'date':'20261002','open':'100','high':'110','low':'90','close':'105','jdiff_vol':'12','value':'3'}]}
        if tr=='t8451':
            return {'rows':[{'date':'20261002','open':'100','high':'110','low':'90','close':'105','jdiff_vol':'12','value':'3'}]}
        if tr=='t1702':
            return {'rows':[{'date':'20261002','close':'105','tjj0000':'1','tjj0018':'2'}]}
        raise AssertionError(tr)


class FakeRepo:
    def __init__(self): self.closed=False; self.members=[]; self.investor={}; self.investor_days=set(); self.venue=[]
    def initialize(self): pass
    def close(self): self.closed=True
    def latest_market_date(self): return dt.date(2026,10,2)
    def upsert_sector_master(self,rows): return len(rows)
    def upsert_security_master(self,rows): return len(rows)
    def replace_index_membership(self,as_of,sector_code,sector_name,rows): self.members.append((sector_code,sector_name)); return len(rows)
    def upsert_sector_daily(self,sector_code,rows): return len(rows)
    def completed_sector_codes(self,as_of): return set()
    def list_stock_codes(self,ticker=None,limit=0): return [ticker or '005930']
    def list_stock_trade_dates(self,stock_code,start,end): return [dt.date(2026,10,2)]
    def stock_trade_dates_by_code(self,stock_codes,start,end): return {code:{dt.date(2026,10,2)} for code in stock_codes}
    def completed_investor_dates(self,*args,**kwargs): return set(self.investor_days)
    def completed_investor_dates_by_code(self,stock_codes,start,end,exchange_code='K'):
        return {code:set(self.investor_days) for code in stock_codes if self.investor_days}
    def upsert_investor_raw(self,stock_code,found,complete_days,exchange_code='K'):
        self.investor[stock_code]=(found,tuple(complete_days)); self.investor_days.update(complete_days); return len(complete_days)
    def latest_venue_date(self,stock_code,venue): return None
    def list_venue_trade_dates(self,stock_code,venue,start,end):
        return {dt.date(2026,10,2)} if any(c==stock_code and v==venue and n for c,v,n in self.venue) else set()
    def venue_trade_dates_by_code(self,stock_codes,venues,start,end):
        return {(code,venue):self.list_venue_trade_dates(code,venue,start,end)
                for code in stock_codes for venue in venues if self.list_venue_trade_dates(code,venue,start,end)}
    def upsert_venue_daily(self,stock_code,venue,rows): self.venue.append((stock_code,venue,len(rows))); return len(rows)


def verify():
    day=dt.date(2026,10,2)

    b=FakeBridge(); r=FakeRepo(); s=XingDbMenuService(b,r); s.__enter__()
    report=s.run_menu2(as_of=day,enforce_cutoff=False)
    assert report.passed, report
    assert {x[0] for x in r.members}=={'101','301'}
    assert report.stages[2].affected_rows==350
    assert sum(1 for tr,_ in b.calls if tr=='t8429')==2
    s.close()

    b=FakeBridge(); r=FakeRepo(); s=XingDbMenuService(b,r); s.__enter__()
    report=s.run_menu5(start=day,end=day,ticker='005930',enforce_cutoff=False)
    assert report.passed, report
    found,complete=r.investor['005930']
    assert len(found)==4 and complete==(day,)
    assert sum(1 for tr,_ in b.calls if tr=='t1702')==4
    s.close()

    b=FakeBridge(); r=FakeRepo(); s=XingDbMenuService(b,r); s.__enter__()
    report=s.run_menu7(start=day,end=day,ticker='005930',enforce_cutoff=False)
    assert report.passed, report
    assert {v for _,v,_ in r.venue}=={'NXT','COMBINED'}
    assert sum(1 for tr,_ in b.calls if tr=='t8451')==2
    assert sum(1 for tr,_ in b.calls if tr=='t1702')==4
    s.close()

    print('V40_XING_DB_INTEGRATION_CHECK: PASS')

if __name__=='__main__': verify()
