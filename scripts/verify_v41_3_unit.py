from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "src"))

import importlib.util

_rate_path = ROOT / "src/krx_research/infrastructure/xing_db/rate_limited_bridge.py"
_spec = importlib.util.spec_from_file_location("v41_3_rate_limited_bridge", _rate_path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
RateLimitedRawTrBridge = _mod.RateLimitedRawTrBridge

from krx_research.application.xing_db.service import XingDbMenuService


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []
    def __call__(self) -> float:
        return self.now
    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FlakyBridge:
    def __init__(self) -> None:
        self.calls = 0
    def connect(self) -> None: pass
    def close(self) -> None: pass
    def raw_tr(self, tr, values):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(f"XingBridgeError: XingDllError: {tr} ETK_Request 실패: 0: rate")
        return {"rows": [{"shcode": "005930"}], "header": {}}


clock = Clock()
flaky = FlakyBridge()
bridge = RateLimitedRawTrBridge(flaky, sleep_fn=clock.sleep, clock_fn=clock)
out = bridge.raw_tr("t1516", {"upcode":"101","gubun":"1","shcode":""})
assert out["rows"] and flaky.calls == 2, (out, flaky.calls)
assert any(s >= 1.0 for s in clock.sleeps), clock.sleeps

# Same-TR pacing must happen even after a successful call.
clock.sleeps.clear()
bridge.raw_tr("t1516", {"upcode":"101","gubun":"1","shcode":""})
assert clock.sleeps and clock.sleeps[0] > 0, clock.sleeps


class Repo:
    def initialize(self): pass
    def close(self): pass
    def latest_market_date(self): return DAY
    def list_stock_codes(self, ticker=None, limit=0): return [ticker or "005930"]
    def list_stock_trade_dates(self, code, start, end): return [end]
    def stock_trade_dates_by_code(self, stock_codes, start, end): return {code:{end} for code in stock_codes}
    def completed_investor_dates(self, code, start, end, exchange_code="K"): return {end}
    def completed_investor_dates_by_code(self, stock_codes, start, end, exchange_code="K"):
        return {code:{end} for code in stock_codes}
    def upsert_investor_raw(self, *a, **k): return 0


class AlwaysFail:
    def connect(self): pass
    def close(self): pass
    def raw_tr(self, tr, values):
        raise RuntimeError(f"{tr} ETK_Request 실패")

DAY = dt.date(2026, 10, 2)
svc = XingDbMenuService(AlwaysFail(), Repo())
report = svc.run_menu5(start=DAY, end=DAY, ticker="005930", chunk_days=1,
                       enforce_cutoff=False, force_refresh=True)
assert not report.passed, report
assert any("요청실패" in s.message for s in report.stages), report.stages
print("V41_3_UNIT_CHECK: PASS")
