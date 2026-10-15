from __future__ import annotations

import datetime as dt
import unittest

from krx_research.application.xing_db.service import XingDbMenuService


DAY = dt.date(2026, 10, 12)


class _Repository:
    def __init__(self) -> None:
        self.completed: dict[tuple[str, str], set[dt.date]] = {}

    def latest_market_date(self) -> dt.date:
        return DAY

    def list_stock_codes(self, _ticker=None, _limit=0) -> list[str]:
        return ["005610", "066360"]

    def replace_cloud_stock_universe(self, _rows) -> int:
        return 2

    def list_cloud_stock_codes(self, _ticker=None, _limit=0, _offset=0) -> list[str]:
        return ["005610", "066360"]

    def stock_trade_dates_by_code(self, codes, _start, _end):
        return {code: {DAY} for code in codes}

    def venue_trade_dates_by_code(self, _codes, _venues, _start, _end):
        return {key: set(days) for key, days in self.completed.items()}

    def upsert_venue_daily(self, code, venue, rows) -> int:
        dates = {
            dt.datetime.strptime(str(row["date"]), "%Y%m%d").date()
            for row in rows
        }
        target = self.completed.setdefault((code, venue), set())
        before = len(target)
        target.update(dates)
        return len(target) - before


class _TransientBridge:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.calls: dict[tuple[str, str], int] = {}

    def raw_tr(self, tr, values):
        if tr == "t8436":
            return {"rows": [
                {"shcode": "005610", "hname": "A"},
                {"shcode": "066360", "hname": "B"},
            ]}
        key = (values["shcode"], values["exchgubun"])
        self.calls[key] = self.calls.get(key, 0) + 1
        if self.always_fail or self.calls[key] == 1:
            raise RuntimeError("temporary HTTP 500")
        return {"rows": [{"date": "20261012"}]}

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass


class Menu7RepairTests(unittest.TestCase):
    def test_independent_target_does_not_read_local_price_dates(self) -> None:
        repository = _Repository()
        repository.latest_market_date = lambda: self.fail("local latest-date dependency")
        repository.stock_trade_dates_by_code = lambda *_: self.fail("local price dependency")
        report = XingDbMenuService(_TransientBridge(), repository).run_menu7(
            start=DAY, end=DAY, include_investor=False, independent_target=True
        )

        self.assertTrue(report.passed)
        self.assertEqual(4, len(repository.completed))

    def test_repairs_only_unresolved_stock_and_venue_pairs(self) -> None:
        repository = _Repository()
        progress: list[str] = []
        report = XingDbMenuService(_TransientBridge(), repository).run_menu7(
            start=DAY,
            end=DAY,
            progress=progress.append,
            include_investor=False,
        )

        self.assertTrue(report.passed)
        self.assertEqual(4, len(repository.completed))
        self.assertTrue(all(days == {DAY} for days in repository.completed.values()))
        self.assertTrue(any("[REPAIR 1/3]" in line for line in progress))

    def test_fails_after_repair_passes_cannot_fill_the_gap(self) -> None:
        repository = _Repository()
        bridge = _TransientBridge(always_fail=True)
        report = XingDbMenuService(bridge, repository).run_menu7(
            start=DAY,
            end=DAY,
            include_investor=False,
        )

        self.assertFalse(report.passed)
        self.assertEqual({}, repository.completed)
        self.assertEqual(16, sum(bridge.calls.values()))


if __name__ == "__main__":
    unittest.main()
