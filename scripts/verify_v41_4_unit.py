from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_db.service import XingDbMenuService

DAY = dt.date(2026, 10, 2)

class Bridge:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, str]]] = []
    def connect(self): pass
    def close(self): pass
    def raw_tr(self, tr, values):
        self.calls.append((tr, dict(values)))
        if tr == "t8424":
            return {"rows": [
                {"upcode":"101","hname":"코스피200"},
                {"upcode":"301","hname":"코스닥150"},
                {"upcode":"001","hname":"종합"},
            ]}
        if tr == "t8436":
            return {"rows": [{"shcode":"005930","hname":"삼성전자"}]}
        if tr == "t1516":
            up = values["upcode"]
            n = 201 if up == "101" else 150
            return {"rows": [{"shcode":f"{i:06d}"} for i in range(1, n+1)]}
        if tr == "t8429":
            return {"rows": [
                {"date":"20261001","close":"100"},
                {"date":"20261002","close":"101"},
            ]}
        raise AssertionError(tr)

class Repo:
    def initialize(self): pass
    def close(self): pass
    def latest_market_date(self): return DAY
    def upsert_sector_master(self, rows): return len(rows)
    def upsert_security_master(self, rows): return len(rows)
    def replace_index_membership(self, as_of, code, display, rows): return len(rows)
    def upsert_sector_daily(self, code, rows):
        assert all(r["date"] == "20261002" for r in rows), rows
        return len(rows)

bridge=Bridge()
repo=Repo()
svc=XingDbMenuService(bridge, repo)
report=svc.run_menu2(as_of=DAY, enforce_cutoff=False)
assert report.passed, report
calls=[v for tr,v in bridge.calls if tr=="t8429"]
assert calls, bridge.calls
for v in calls:
    assert v["qrycnt"] == "200", v
    assert v["sdate"] == "20260818", v
    assert v["edate"] == "20261002", v
print("V41_4_UNIT_CHECK: PASS")
