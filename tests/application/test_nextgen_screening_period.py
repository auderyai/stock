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

    def period_trade_dates(self, start, end, *, weekly=False):
        return [value for value in self.dates if start <= value <= end]

    def latest_trade_date(self):
        return self.dates[-1]

    def earliest_trade_date(self):
        return self.dates[0]

    def run(self, _query):
        self.ran = True
        return []


class NextgenScreeningPeriodTests(unittest.TestCase):
    def test_general_screen_checks_both_boundaries_against_database_dates(self):
        repository = _Repository(["2026-10-07", "2026-10-08"])
        service = ScreeningService(repository)
        query = ScreeningQuery(ScreeningKind.DAILY_GAINERS, as_of_date="2026-10-08")
        with self.assertRaisesRegex(ValueError, "DB에 없는 날짜: 2026-10-06"):
            service.run(query, period=DateRange(date(2026, 10, 6), date(2026, 10, 8)))
        self.assertFalse(repository.ran)

    def test_general_screen_runs_when_start_and_end_are_stored_dates(self):
        repository = _Repository(["2026-10-07", "2026-10-08"])
        service = ScreeningService(repository)
        query = ScreeningQuery(ScreeningKind.DAILY_GAINERS, as_of_date="2026-10-08")
        service.run(query, period=DateRange(date(2026, 10, 7), date(2026, 10, 8)))
        self.assertTrue(repository.ran)

    def test_status_exposes_only_database_trade_dates(self):
        service = ScreeningService(_Repository(["2026-10-07", "2026-10-08"]))
        self.assertEqual(service.status()["trade_dates"], ["2026-10-07", "2026-10-08"])


if __name__ == "__main__":
    unittest.main()
