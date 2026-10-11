from __future__ import annotations
import datetime as dt,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from krx_research.collectors.index_membership import INDEX_GAINER_DEFINITIONS,IndexMembership
from krx_research.collectors.ls_index_api import LSIndexClient
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.index_membership_store import PostgreSQLIndexMembershipStore
from krx_research.data_engine.postgresql import BaseDataRepository

def norm(x): return re.sub(r"[\s_-]+","",str(x)).upper()
def get_members(client,aliases,expected):
    wanted={norm(x) for x in aliases}; codes=set()
    for group in ("0","","1","2"):
        for row in client._call("t8424","",{"gubun1":group})["t8424OutBlock"]:
            if norm(row.get("hname")) in wanted:
                c=str(row.get("upcode","")).strip()
                if len(c)==3 and c.isdigit(): codes.add(c)
        if codes: break
    if len(codes)!=1: raise ValueError(f"지수코드 일치 오류: {sorted(codes)}")
    upcode=codes.pop(); rows=client._call("t1516","",{"upcode":upcode,"gubun":"1","shcode":""})["t1516OutBlock1"]
    tickers=tuple(sorted({str(r.get("shcode","")).strip().upper() for r in rows if re.fullmatch(r"[0-9A-Z]{6}",str(r.get("shcode","")).strip().upper())}))
    if len(tickers)!=expected: raise ValueError(f"구성종목 수 오류: {len(tickers)}/{expected}")
    return upcode,tickers

def main():
    settings=DataEngineSettings.from_environment(); store=PostgreSQLIndexMembershipStore(settings); store.initialize()
    with BaseDataRepository(settings,application_name="index_membership_date") as repo: day=repo.latest_ohlcv_date() or dt.date.today()
    with LSIndexClient(project_root=ROOT) as client:
        for key,d in INDEX_GAINER_DEFINITIONS.items():
            aliases={"KOSPI200","코스피200"} if d.market=="KOSPI" else {"KOSDAQ150","코스닥150"}; code,tickers=get_members(client,aliases,d.expected_count)
            n=store.upsert(IndexMembership(key,code,d.display_name,day,tickers,"LS_XING32:t8424+t1516")); print(f"{d.display_name}: {day} {n}종목 저장",flush=True)
    return 0
if __name__=="__main__": raise SystemExit(main())
