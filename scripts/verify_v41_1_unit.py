from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from krx_research.application.xing_db.e2e_models import CommandOutcome,Menu2Snapshot,WriteCandidate
from krx_research.application.xing_db.e2e_service import DbMenuE2EVerificationService
from krx_research.application.xing_db.service import XingDbMenuService

DAY=dt.date(2026,10,2)

class Probe:
    def __init__(self): self.combined=1; self.raw=4; self.cp=1; self.menu2_runs=0
    def latest_market_date(self): return DAY
    def find_combined_gap(self,s,e): return None
    def find_existing_combined(self,s,e): return WriteCandidate("005930",DAY,"existing")
    def combined_row_count(self,c,d): return self.combined
    def find_investor_gap(self,s,e): return None
    def find_completed_investor(self,s,e): return WriteCandidate("005930",DAY,"complete")
    def investor_matrix_count(self,c,d): return self.raw
    def investor_checkpoint_count(self,c,d): return self.cp
    def menu2_snapshot(self,a):
        if self.menu2_runs==0: return Menu2Snapshot(a,252,4306,0,0,0,0,0,0,0)
        return Menu2Snapshot(a,252,4306,201,150,252,0,0,0,0)
    def close(self): pass
class Commands:
    def __init__(self,p): self.p=p
    def run_menu7_single_combined(self,c,d,force_refresh=False): return CommandOutcome(0,1)
    def run_menu5_single_day(self,c,d,force_refresh=False): return CommandOutcome(0,4)
    def run_menu2_full(self,a): self.p.menu2_runs+=1; return CommandOutcome(0,0)

class Bridge:
    def __init__(self): self.calls=[]
    def connect(self): pass
    def close(self): pass
    def raw_tr(self,tr,values):
        self.calls.append((tr,dict(values)))
        if tr=="t1702":
            return {"rows":[{"date":"20261002","tjj0000_vol":"1"}]}
        return {"rows":[]}
class Repo:
    def initialize(self): pass
    def close(self): pass

def main()->int:
    p=Probe()
    results=DbMenuE2EVerificationService(p,Commands(p)).run_all(lookback_days=30)
    assert len(results)==3 and all(r.passed for r in results), results
    # Single-day t1702 must expand wire query range by 28 days.
    b=Bridge(); s=XingDbMenuService(b,Repo())
    found,complete=s._collect_t1702("005930",[DAY])
    assert len(b.calls)==4
    assert all(v["fromdt"]=="20260904" and v["todt"]=="20261002" for _,v in b.calls), b.calls
    assert complete==[DAY]
    print("V41_1_UNIT_CHECK: PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
