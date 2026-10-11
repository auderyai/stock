from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_db.service import XingDbMenuService


DAY = dt.date(2026, 10, 2)


class FakeBridge:
    def __init__(self, *, empty_t8451: bool = False, empty_t1702: bool = False):
        self.connected = False
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.empty_t8451 = empty_t8451
        self.empty_t1702 = empty_t1702

    def connect(self): self.connected = True
    def close(self): self.connected = False

    def raw_tr(self, tr, values):
        self.calls.append((tr, dict(values)))
        if tr == "t8451":
            if self.empty_t8451:
                return {"rows": []}
            return {"rows": [{"date": "20261002", "open": "100", "high": "110", "low": "90",
                              "close": "105", "jdiff_vol": "12", "value": "3"}]}
        if tr == "t1702":
            if self.empty_t1702:
                return {"rows": []}
            return {"rows": [{"date": "20261002", "close": "105", "tjj0000": "1"}]}
        raise AssertionError(tr)


class FakeRepo:
    def __init__(self, *, base_days=True, combined_complete=False, investor_complete=False):
        self.base_days = base_days
        self.venue: dict[tuple[str, str], set[dt.date]] = {}
        self.investor: set[dt.date] = set()
        if combined_complete:
            self.venue[("005930", "COMBINED")] = {DAY}
        if investor_complete:
            self.investor = {DAY}

    def initialize(self): pass
    def close(self): pass
    def latest_market_date(self): return DAY
    def upsert_sector_master(self, rows): return len(rows)
    def upsert_security_master(self, rows): return len(rows)
    def replace_index_membership(self, *args): return len(args[-1])
    def upsert_sector_daily(self, sector_code, rows): return len(rows)
    def list_stock_codes(self, ticker=None, limit=0): return [ticker or "005930"]
    def list_stock_trade_dates(self, stock_code, start, end): return [DAY] if self.base_days else []
    def stock_trade_dates_by_code(self, stock_codes, start, end):
        return {code: {DAY} for code in stock_codes} if self.base_days else {}
    def completed_investor_dates(self, stock_code, start, end, exchange_code="K"):
        return set(self.investor)
    def completed_investor_dates_by_code(self, stock_codes, start, end, exchange_code="K"):
        return {code: set(self.investor) for code in stock_codes if self.investor}
    def upsert_investor_raw(self, stock_code, found, complete_days, exchange_code="K"):
        self.investor.update(complete_days)
        return len(complete_days)
    def latest_venue_date(self, stock_code, venue):
        values = self.venue.get((stock_code, venue), set())
        return max(values) if values else None
    def list_venue_trade_dates(self, stock_code, venue, start, end):
        return {d for d in self.venue.get((stock_code, venue), set()) if start <= d <= end}
    def venue_trade_dates_by_code(self, stock_codes, venues, start, end):
        return {(code, venue): self.list_venue_trade_dates(code, venue, start, end)
                for code in stock_codes for venue in venues if self.list_venue_trade_dates(code, venue, start, end)}
    def upsert_venue_daily(self, stock_code, venue, rows):
        dates = set()
        for row in rows:
            value = str(row.get("date") or "")
            if value:
                dates.add(dt.datetime.strptime(value, "%Y%m%d").date())
        self.venue.setdefault((stock_code, venue), set()).update(dates)
        return len(dates)


def run_service(bridge, repo, *, include_investor=True):
    service = XingDbMenuService(bridge, repo)
    service.__enter__()
    try:
        return service.run_menu7(
            start=DAY, end=DAY, ticker="005930", venues=("NXT", "COMBINED"),
            enforce_cutoff=False, include_investor=include_investor,
        )
    finally:
        service.close()


def verify():
    # Normal rows: PASS and DB validation succeeds.
    report = run_service(FakeBridge(), FakeRepo())
    assert report.passed, report
    assert report.stages[0].affected_rows == 2
    assert report.stages[1].affected_rows == 4

    # No base KRX dates in the selected period: legitimate SKIP.
    report = run_service(FakeBridge(), FakeRepo(base_days=False))
    assert report.passed, report

    # COMBINED empty response with a required KRX date: must FAIL.
    report = run_service(FakeBridge(empty_t8451=True), FakeRepo(), include_investor=False)
    assert not report.passed, report

    # Existing complete DB: legitimate zero-row SKIP is allowed and explicitly labelled.
    bridge = FakeBridge()
    repo = FakeRepo(combined_complete=True, investor_complete=True)
    report = run_service(bridge, repo)
    assert report.passed, report
    assert report.stages[1].message.startswith("SKIP"), report.stages[1]

    # Empty t1702 with a real pending trade date: must FAIL after checkpoint re-read.
    report = run_service(FakeBridge(empty_t1702=True), FakeRepo())
    assert not report.passed, report
    assert not report.stages[1].passed

    print("V40_3_ZERO_ROW_VALIDATION_CHECK: PASS")


if __name__ == "__main__":
    verify()
