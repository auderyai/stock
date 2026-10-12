from __future__ import annotations

import datetime as dt
import unittest

from krx_research.application.xing_db.service import XingDbMenuService


DAY = dt.date(2026, 10, 12)


class _Repository:
    def __init__(self) -> None:
        self.completed: set[dt.date] = set()

    def latest_market_date(self) -> dt.date:
        return DAY

    def list_stock_codes(self, _ticker=None, _limit=0) -> list[str]:
        return ["001450"]

    def stock_trade_dates_by_code(self, _codes, _start, _end):
        return {"001450": {DAY}}

    def completed_investor_dates_by_code(self, _codes, _start, _end, _exchange="K"):
        return {"001450": set(self.completed)} if self.completed else {}

    def upsert_investor_raw(self, _code, _found, complete, _exchange="K") -> int:
        before = len(self.completed)
        self.completed.update(complete)
        return len(self.completed) - before


class _TransientBridge:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.failures = 0

    def raw_tr(self, _tr, values):
        if values["volvalgb"] == "0" and values["msmdgb"] == "1":
            if self.always_fail or self.failures == 0:
                self.failures += 1
                raise RuntimeError("temporary HTTP 500")
        return {"rows": [{"date": "20261012", "tjj0000_vol": "1"}]}

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass


class Menu5RepairTests(unittest.TestCase):
    def test_repairs_only_unresolved_stock_after_transient_failure(self) -> None:
        repository = _Repository()
        progress: list[str] = []
        report = XingDbMenuService(_TransientBridge(), repository).run_menu5(
            start=DAY,
            end=DAY,
            progress=progress.append,
        )

        self.assertTrue(report.passed)
        self.assertEqual({DAY}, repository.completed)
        self.assertIn("일시 요청실패 1회 복구", report.stages[0].message)
        self.assertTrue(any("[REPAIR 1/3]" in line for line in progress))

    def test_fails_when_repair_passes_cannot_fill_the_gap(self) -> None:
        repository = _Repository()
        report = XingDbMenuService(
            _TransientBridge(always_fail=True), repository
        ).run_menu5(start=DAY, end=DAY)

        self.assertFalse(report.passed)
        self.assertEqual(set(), repository.completed)
        self.assertIn("미완료 1건/거래일", report.stages[0].message)
        self.assertIn("요청실패 4회", report.stages[0].message)


if __name__ == "__main__":
    unittest.main()
