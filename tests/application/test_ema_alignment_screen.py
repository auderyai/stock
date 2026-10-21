from __future__ import annotations

from datetime import date, timedelta
import unittest

import pandas as pd

from krx_research_nextgen.models.screen_catalog import SCREENS, SCREEN_UNIVERSE_POLICY
from krx_research_nextgen.models.screening import DateRange, ScreeningKind, ScreeningQuery
from krx_research_nextgen.services.ema_alignment_strategy import EmaAlignmentStrategy
from krx_research_nextgen.services.screening_service import ScreeningService


def _rows(code: str, closes: list[float]) -> list[dict[str, object]]:
    first = date(2026, 9, 1)
    return [
        {"stock_code": code, "stock_name": code, "market": "KOSPI",
         "trade_date": first + timedelta(days=index), "close": close}
        for index, close in enumerate(closes)
    ]


class EmaAlignmentScreenTests(unittest.TestCase):
    def test_catalog_exposes_database_only_screen_with_optional_core_indices(self) -> None:
        spec = next(item for item in SCREENS if item.kind is ScreeningKind.EMA_BEARISH_ALIGNMENT_BREAKOUT)
        self.assertEqual(spec.market, "ALL")
        self.assertTrue(spec.database_only)
        self.assertEqual(SCREEN_UNIVERSE_POLICY.resolve(spec.market, False), "ALL")
        self.assertEqual(SCREEN_UNIVERSE_POLICY.resolve(spec.market, True), "KOSPI200+KOSDAQ150")

    def test_configured_core_index_screen_remains_core_when_unchecked(self) -> None:
        self.assertEqual(
            SCREEN_UNIVERSE_POLICY.resolve("KOSPI200+KOSDAQ150", False),
            "KOSPI200+KOSDAQ150",
        )

    def test_requires_full_period_alignment_and_latest_close_breakout(self) -> None:
        descending = [130.0 - index for index in range(29)]
        frame = pd.DataFrame(
            _rows("000001", descending + [150.0])
            + _rows("000002", descending + [90.0])
            + [row for row in _rows("000003", descending + [150.0])
               if row["trade_date"] != date(2026, 9, 25)]
        )

        rows = EmaAlignmentStrategy().select(
            frame, start=date(2026, 9, 21), end=date(2026, 9, 29),
            latest=date(2026, 9, 30), limit=50,
        )

        self.assertEqual([row.stock_code for row in rows], ["000001"])
        self.assertEqual(rows[0].trade_date, "2026-09-30")

    def test_service_reads_through_repository_with_latest_database_date(self) -> None:
        descending = [130.0 - index for index in range(29)]

        class Repository:
            ohlcv_relation = "market.ohlcv_daily"
            master_relation = "market.security_master"
            last_metrics = {}

            def period_trade_dates(self, start, end, *, weekly=False):
                return ["2026-09-21", "2026-09-22", "2026-09-23"]

            def latest_trade_date(self):
                return "2026-09-30"

            def ema_alignment_input(self, start, latest, universe):
                self.arguments = start, latest, universe
                return pd.DataFrame(_rows("000001", descending + [150.0]))

            @staticmethod
            def enrich_display_fields(rows):
                return rows

        repository = Repository()
        period = DateRange(date(2026, 9, 20), date(2026, 9, 29))
        rows = ScreeningService(repository).run(
            ScreeningQuery(
                ScreeningKind.EMA_BEARISH_ALIGNMENT_BREAKOUT,
                market="KOSPI200+KOSDAQ150", as_of_date="2026-09-29",
            ),
            period=period,
        )

        self.assertEqual(repository.arguments, ("2026-09-20", "2026-09-30", "KOSPI200+KOSDAQ150"))
        self.assertEqual([row.stock_code for row in rows], ["000001"])

    def test_calendar_period_requires_at_least_one_stored_session(self) -> None:
        class Repository:
            ohlcv_relation = "market.ohlcv_daily"
            master_relation = "market.security_master"
            last_metrics = {}

            @staticmethod
            def period_trade_dates(start, end, *, weekly=False):
                return []

            @staticmethod
            def latest_trade_date():
                return "2026-10-20"

        with self.assertRaisesRegex(ValueError, "달력 구간 안에 PostgreSQL 거래일"):
            ScreeningService(Repository()).run(
                ScreeningQuery(ScreeningKind.EMA_BEARISH_ALIGNMENT_BREAKOUT),
                period=DateRange(date(2026, 10, 3), date(2026, 10, 5)),
            )


if __name__ == "__main__":
    unittest.main()
