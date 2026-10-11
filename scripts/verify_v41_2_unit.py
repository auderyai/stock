from __future__ import annotations
import datetime as dt
import ast
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from krx_research.application.xing_db.service import XingDbMenuService

DAY=dt.date(2026,10,2)

class Bridge:
    def __init__(self): self.calls=[]
    def connect(self): pass
    def close(self): pass
    def raw_tr(self,tr,values):
        self.calls.append((tr,dict(values)))
        if tr=="t1702":
            return {"rows":[{"date":"20261002","tjj0000_vol":"1"}]}
        if tr=="t8451":
            return {"rows":[
                {"date":"20260920","close":"1"},
                {"date":"20261002","close":"2"},
            ]}
        return {"rows":[]}
class Repo:
    def initialize(self): pass
    def close(self): pass

def main()->int:
    # Execute the actual repository helper methods without opening PostgreSQL.
    repo_path=ROOT/"src/krx_research/infrastructure/xing_db/postgresql_repository.py"
    tree=ast.parse(repo_path.read_text(encoding="utf-8"))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="PostgreSQLXingMenuRepository")
    methods=[n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {"_json_dumps","_json_safe"}]
    mini=ast.Module(body=[ast.Import(names=[ast.alias(name="json")]), ast.ClassDef(name="Mini",bases=[],keywords=[],decorator_list=[],body=methods)], type_ignores=[])
    ns={}
    exec(compile(ast.fix_missing_locations(mini),"<repo_helpers>","exec"),ns)
    payload=ns["Mini"]._json_dumps({"a":"x\x00y","nested":["z\x00q"]})
    assert "\\u0000" not in payload and "\x00" not in payload
    decoded=json.loads(payload)
    assert decoded=={"a":"xy","nested":["zq"]}

    svc=XingDbMenuService(Bridge(),Repo())
    assert svc._expanded_request_start(DAY,DAY)==dt.date(2026,8,18)
    rows=svc._filter_rows_by_date([
        {"date":"20260920"},{"date":"20261002"},{"date":"bad"}
    ],DAY,DAY)
    assert rows==[{"date":"20261002"}]

    found,complete=svc._collect_t1702("005930",[DAY])
    calls=svc._bridge.calls
    assert len(calls)==4
    assert all(v["fromdt"]=="20260818" and v["todt"]=="20261002" for _,v in calls), calls
    assert complete==[DAY]
    print("V41_2_UNIT_CHECK: PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
