from __future__ import annotations
from pathlib import Path
import pandas as pd
from .xing.bridge import XingBridgeClient
T8451_VENUES={"KRX":"K","NXT":"N","COMBINED":"U"}
def normalize_t8451_rows(rows,*,ticker,venue):
    records=[]
    for row in rows:
        stamp=str(row.get("date","")).strip()
        if len(stamp)!=8 or not stamp.isdigit(): continue
        records.append({"stock_code":str(ticker).zfill(6),"trade_date":pd.to_datetime(stamp,format="%Y%m%d"),"open_price":int(float(row.get("open") or 0)),"high_price":int(float(row.get("high") or 0)),"low_price":int(float(row.get("low") or 0)),"close_price":int(float(row.get("close") or 0)),"volume":int(float(row.get("jdiff_vol") or 0)),"amount":int(float(row.get("value") or 0))*1_000_000,"source":f"LS_XING32:t8451:{venue.upper()}"})
    f=pd.DataFrame(records); return f.sort_values("trade_date").drop_duplicates("trade_date",keep="last") if not f.empty else f
class XingT8451Client:
    def __init__(self,project_root:str|Path,*,timeout:float=30.0,delay:float=.08): self.bridge=XingBridgeClient(project_root,delay=delay,timeout=timeout)
    @classmethod
    def from_environment(cls,project_root,**kwargs): return cls(project_root,**kwargs)
    def connect(self): self.bridge.connect()
    def close(self): self.bridge.close()
    def __enter__(self): self.connect(); return self
    def __exit__(self,*_): self.close()
    def fetch(self,ticker,start,end,venue,*,page_size=200):
        selected=venue.upper()
        if selected not in T8451_VENUES: raise ValueError(f"지원하지 않는 거래시장: {venue}")
        r=self.bridge.raw_tr("t8451",{"shcode":str(ticker).zfill(6),"gubun":"2","qrycnt":str(max(1,min(page_size,2000))),"sdate":start.strftime("%Y%m%d"),"edate":end.strftime("%Y%m%d"),"cts_date":"","comp_yn":"N","sujung":"N","exchgubun":T8451_VENUES[selected]})
        return normalize_t8451_rows(r["rows"],ticker=ticker,venue=selected)
