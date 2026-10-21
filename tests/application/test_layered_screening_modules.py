import datetime as dt
import unittest

import pandas as pd

from krx_research.analytics.screening import (
    build_market_gainer_rows,
    select_period_screen_dates,
)
from krx_research.collectors.naver_investor import fetch_naver_investor_trend
from krx_research.policies.screen_catalog import DAILY_GAINER_SCREEN_TYPES


class LayeredScreeningModuleTests(unittest.TestCase):
    def test_daily_dates_preserve_each_stored_session(self):
        dates = [dt.date(2026, 10, 12), dt.date(2026, 10, 13)]
        self.assertEqual(
            select_period_screen_dates(
                dates, start=dates[0], end=dates[-1],
                screen_type="kospi_daily_gainers",
            ),
            dates,
        )

    def test_weekly_dates_keep_last_stored_session_per_week(self):
        dates = [
            dt.date(2026, 10, 12), dt.date(2026, 10, 16),
            dt.date(2026, 10, 19), dt.date(2026, 10, 20),
        ]
        self.assertEqual(
            select_period_screen_dates(
                dates, start=dates[0], end=dates[-1],
                screen_type="weekly_return",
            ),
            [dt.date(2026, 10, 16), dt.date(2026, 10, 20)],
        )

    def test_market_ranking_is_numeric_and_has_deterministic_tie_break(self):
        snapshot = pd.DataFrame([
            {"ticker": "000002", "name": "B", "market": "KOSPI",
             "trade_date": "2026-10-16", "close": 100,
             "daily_return_pct": "2.5", "estimated_trading_value": 1000},
            {"ticker": "000001", "name": "A", "market": "KOSPI",
             "trade_date": "2026-10-16", "close": 100,
             "daily_return_pct": "2.5", "estimated_trading_value": 1000},
            {"ticker": "000003", "name": "C", "market": "KOSDAQ",
             "trade_date": "2026-10-16", "close": 100,
             "daily_return_pct": "9.0", "estimated_trading_value": 5000},
        ])
        rows = build_market_gainer_rows(snapshot, "kospi_daily_gainers")
        self.assertEqual(rows["ticker"].tolist(), ["000001", "000002"])
        self.assertEqual(rows["rank"].tolist(), [1, 2])

    def test_screen_catalog_contains_daily_market_screens(self):
        self.assertIn("kospi_daily_gainers", DAILY_GAINER_SCREEN_TYPES)
        self.assertIn("kospi_kosdaq_daily_trading_value", DAILY_GAINER_SCREEN_TYPES)

    def test_naver_collector_rejects_invalid_code_without_network(self):
        with self.assertRaises(ValueError):
            fetch_naver_investor_trend("not-a-code")


if __name__ == "__main__":
    unittest.main()
