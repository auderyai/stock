from datetime import date
import unittest

from krx_research_nextgen.models.screening import DateRange, ScreeningKind, ScreeningQuery
from krx_research_nextgen.services.screening_service import ScreeningService


class _Repository:
    ohlcv_relation = "market.ohlcv_daily"
    master_relation = "market.security_master"
    last_metrics = {}

    def __init__(self, dates):
        self.dates = dates
        self.ran = False
        self.as_of_date = None

    def period_trade_dates(self, start, end, *, weekly=False):
        return [value for value in self.dates if start <= value <= end]

    def latest_trade_date(self):
        return self.dates[-1]

    def earliest_trade_date(self):
        return self.dates[0]

    def daily_gainers(self, query):
        self.ran = True
        self.as_of_date = query.as_of_date
        return []

    @staticmethod
    def enrich_display_fields(rows):
        return rows


class NextgenScreeningPeriodTests(unittest.TestCase):
    def test_general_screen_accepts_calendar_boundaries_and_uses_last_stored_date(self):
        repository = _Repository(["2026-10-07", "2026-10-08", "2026-10-10"])
        service = ScreeningService(repository)
        query = ScreeningQuery(ScreeningKind.DAILY_GAINERS, as_of_date="2026-10-09")
        service.run(query, period=DateRange(date(2026, 10, 6), date(2026, 10, 9)))
        self.assertTrue(repository.ran)
        self.assertEqual(repository.as_of_date, "2026-10-08")

    def test_general_screen_runs_when_start_and_end_are_stored_dates(self):
        repository = _Repository(["2026-10-07", "2026-10-08"])
        service = ScreeningService(repository)
        query = ScreeningQuery(ScreeningKind.DAILY_GAINERS, as_of_date="2026-10-08")
        service.run(query, period=DateRange(date(2026, 10, 7), date(2026, 10, 8)))
        self.assertTrue(repository.ran)

    def test_general_screen_rejects_period_without_stored_dates(self):
        repository = _Repository(["2026-10-07", "2026-10-08"])
        with self.assertRaisesRegex(ValueError, "달력 구간 안에 PostgreSQL 거래일"):
            ScreeningService(repository).run(
                ScreeningQuery(ScreeningKind.DAILY_GAINERS),
                period=DateRange(date(2026, 10, 5), date(2026, 10, 6)),
            )

    def test_bollinger_screen_uses_last_stored_date_inside_calendar_period(self):
        repository = _Repository(["2026-10-07", "2026-10-08", "2026-10-10"])

        class Breadth:
            as_of_date = None

            def run(self, query):
                self.as_of_date = query.as_of_date
                return []

        breadth = Breadth()
        ScreeningService(repository, bollinger_breadth=breadth).run(
            ScreeningQuery(ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT),
            period=DateRange(date(2026, 10, 6), date(2026, 10, 9)),
        )

        self.assertEqual(breadth.as_of_date, "2026-10-08")

    def test_status_exposes_only_database_trade_dates(self):
        service = ScreeningService(_Repository(["2026-10-07", "2026-10-08"]))
        self.assertEqual(service.status()["trade_dates"], ["2026-10-07", "2026-10-08"])


if __name__ == "__main__":
    unittest.main()
