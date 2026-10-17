"""64bit compatibility facade backed by the persistent 32bit xingAPI worker."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import pandas as pd

from krx_research.data_engine.market_indices import LS_INDEX_PRICE_SCALE
from .xing.bridge import XingBridgeClient

def _frame(rows,start,end):
    records=[]
    for item in rows:
        stamp=str(item.get("date","")).strip()
        try:
            day=dt.datetime.strptime(stamp,"%Y%m%d").date()
            p=[float(item.get(x) or 0) / LS_INDEX_PRICE_SCALE
               for x in ("open","high","low","close")]
        except ValueError: continue
        if start<=day<=end and min(p)>0:
            records.append({"date":day,"시가":p[0],"고가":p[1],"저가":p[2],"종가":p[3],"거래량":int(float(item.get("jdiff_vol") or 0)),"LS거래대금원시":float(item.get("value") or 0)})
    return pd.DataFrame(records).drop_duplicates("date",keep="last").set_index("date").sort_index() if records else pd.DataFrame()

class LSIndexClient:
    def __init__(self,*_legacy,delay:float=.08,project_root:str|Path|None=None):
        root=Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[3]; self.bridge=XingBridgeClient(root,delay=max(1.1,delay))
    def __enter__(self): self.bridge.connect(); return self
    def __exit__(self,*_): self.close()
    def close(self): self.bridge.close()
    def sectors(self):
        result={}
        for group in ("0","","1","2"):
            for row in self.bridge.raw_tr("t8424",{"gubun1":group})["rows"]:
                code=str(row.get("upcode","")).strip(); name=str(row.get("hname","")).strip()
                if len(code)==3 and code.isdigit() and name: result[code]=name
            if result: break
        if not result: raise ValueError("xingAPI t8424 업종 목록이 없습니다.")
        return result
    def candles(self,code,start,end):
        r=self.bridge.raw_tr("t8429",{"shcode":code,"gubun":"2","qrycnt":"500","sdate":start.strftime("%Y%m%d"),"edate":end.strftime("%Y%m%d"),"cts_date":"","comp_yn":"N"})
        return _frame(r["rows"],start,end)
    def _call(self,tr,_path,block):
        r=self.bridge.raw_tr(tr,{k:str(v) for k,v in block.items()}); names={"t8424":("t8424OutBlock",None),"t1516":("t1516OutBlock1","t1516OutBlock"),"t8429":("t8429OutBlock1","t8429OutBlock"),"t1702":("t1702OutBlock1",None),"t8436":("t8436OutBlock",None)}
        if tr not in names: raise ValueError(f"지원하지 않는 xingAPI TR: {tr}")
        rows,header=names[tr]; out={rows:r["rows"]}
        if header: out[header]=r.get("header",{})
        return out
