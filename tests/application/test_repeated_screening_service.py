from __future__ import annotations

import unittest
from datetime import date

from krx_research_nextgen.models.screening import (
    DateRange,
    ScreeningKind,
    ScreeningQuery,
    ScreeningResult,
)
from krx_research_nextgen.services.screening_service import ScreeningService


class _Repository:
    ohlcv_relation = "test.ohlcv"
    master_relation = "test.master"
    last_metrics: dict = {}

    def __init__(self, dates: list[str]) -> None:
        self.dates = dates
        self.executed: list[str] = []

    def period_trade_dates(self, *_args, **_kwargs) -> list[str]:
        return self.dates

    def latest_trade_date(self) -> str:
        return self.dates[-1]

    def period_dates_with_membership(self, _market: str, dates: list[str]) -> list[str]:
        return dates

    def run(self, query: ScreeningQuery) -> list[ScreeningResult]:
        self.executed.append(str(query.as_of_date))
        code = "000660" if len(self.dates) > 1 and query.as_of_date == self.dates[1] else "005930"
        return [ScreeningResult(code, code, "KOSPI", str(query.as_of_date), 100.0)]

    def period_stock_metrics(self, codes: list[str], _start: str, _end: str) -> dict:
        return {
            (code, day): {"stock_name": code, "industry": "반도체", "close": 100.0}
            for code in codes for day in self.dates
        }


class RepeatedScreeningServiceTests(unittest.TestCase):
    def test_high_52w_period_returns_each_trade_date_in_order(self) -> None:
        dates = ["2026-10-13", "2026-10-14", "2026-10-15"]
        repository = _Repository(dates)
        rows = ScreeningService(repository).run(
            ScreeningQuery(ScreeningKind.HIGH_52W, 500, "ALL"),
            period=DateRange(date(2026, 10, 13), date(2026, 10, 15)),
        )

        self.assertEqual(repository.executed, dates)
        self.assertEqual([row.trade_date for row in rows], dates)

    def test_single_date_high_52w_keeps_single_day_behavior(self) -> None:
        repository = _Repository(["2026-10-16"])
        rows = ScreeningService(repository).run(
            ScreeningQuery(ScreeningKind.HIGH_52W, 500, "ALL", as_of_date="2026-10-16"),
            period=DateRange(date(2026, 10, 16), date(2026, 10, 16)),
        )

        self.assertEqual(repository.executed, ["2026-10-16"])
        self.assertEqual(rows[0].trade_date, "2026-10-16")

    def test_high_52w_runs_every_trade_date_and_keeps_appearance_dates(self) -> None:
        dates = ["2026-10-13", "2026-10-14", "2026-10-15"]
        repository = _Repository(dates)
        rows = ScreeningService(repository).run_repeated(
            ScreeningQuery(ScreeningKind.HIGH_52W, 500, "ALL"),
            DateRange(date(2026, 10, 13), date(2026, 10, 15)),
        )

        self.assertEqual(repository.executed, dates)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].stock_code, "005930")
        self.assertEqual(rows[0].screen_dates, (dates[0], dates[2]))

    def test_repeated_screen_requires_two_trade_dates(self) -> None:
        repository = _Repository(["2026-10-16"])
        with self.assertRaisesRegex(ValueError, "거래일이 2일 이상"):
            ScreeningService(repository).run_repeated(
                ScreeningQuery(ScreeningKind.HIGH_52W, 500, "ALL"),
                DateRange(date(2026, 10, 16), date(2026, 10, 16)),
            )


if __name__ == "__main__":
    unittest.main()
