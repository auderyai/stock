from types import SimpleNamespace
import unittest

import pandas as pd

from krx_research_nextgen.models.screening import ScreeningKind, ScreeningQuery
from krx_research_nextgen.repositories.realtime_screening_repository import RealtimeScreeningRepository
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.realtime_screening_service import RealtimeScreeningService


class _LiveData:
    def __init__(self): self.call = None

    def load_screen(self, key, **options):
        self.call = key, options
        rows = pd.DataFrame([
            {"ticker": "5930", "name": "삼성전자", "market": "KOSPI", "close": 80_000,
             "daily_return_pct": 2.5, "estimated_trading_value": 100_000_000,
             "high_52w": 82_000, "distance_from_52w_high_pct": -2.44},
            {"ticker": "660", "name": "SK하이닉스", "market": "KOSPI", "close": 200_000,
             "distance_from_52w_high_pct": -12.0},
        ])
        return SimpleNamespace(rows=rows, run={"as_of_date": "2026-10-17"})


class _DatabaseRepository:
    ohlcv_relation = "market.ohlcv_daily"
    master_relation = "market.security_master"
    last_metrics = {}

    def run(self, query): return []
    def latest_trade_date(self): return "2026-10-16"


class RealtimeScreeningRepositoryTests(unittest.TestCase):
    def test_live_source_uses_existing_pipeline_and_converts_rows(self):
        data = _LiveData()
        live = RealtimeScreeningRepository(data)
        query = ScreeningQuery(ScreeningKind.DAILY_GAINERS, 1, "KOSPI", source_mode="realtime", quote_venue="KRX+NXT")
        rows = ScreeningService(_DatabaseRepository(), RealtimeScreeningService(live)).run(query)
        self.assertEqual((rows[0].stock_code, rows[0].trade_date, rows[0].rank), ("005930", "2026-10-17", 1))
        self.assertEqual(data.call[0], "kospi_daily_gainers")
        self.assertEqual(data.call[1]["quote_venue"], "COMBINED")

    def test_live_near_high_applies_requested_range(self):
        data = _LiveData(); live = RealtimeScreeningRepository(data)
        query = ScreeningQuery(ScreeningKind.NEAR_HIGH_52W, 50, "ALL", near_low=-5, near_high=0, source_mode="realtime")
        rows = RealtimeScreeningService(live).run(query)
        self.assertEqual([row.stock_code for row in rows], ["005930"])

    def test_historical_only_screen_gives_clear_message(self):
        with self.assertRaisesRegex(ValueError, "데이터베이스"):
            RealtimeScreeningService(RealtimeScreeningRepository(_LiveData())).run(
                ScreeningQuery(ScreeningKind.EMA_SIMILARITY, source_mode="realtime")
            )


if __name__ == "__main__": unittest.main()
