from datetime import date
import unittest

import pandas as pd

from krx_research.chart_learning.service import ChartPatternFeatureService
from krx_research.chart_learning.repository import ChartLearningRepository


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query, _values):
        return _Rows(self.rows)


class ChartPatternFeatureServiceTests(unittest.TestCase):
    def test_resolves_omitted_ticker_by_exact_unique_company_name(self):
        repository = ChartLearningRepository.__new__(ChartLearningRepository)
        repository.conn = _Connection([{"ticker": "092870", "company_name": "엑시콘"}])
        self.assertEqual(repository.resolve("", "엑시콘")["ticker"], "092870")

    def test_rejects_ambiguous_company_name(self):
        repository = ChartLearningRepository.__new__(ChartLearningRepository)
        repository.conn = _Connection([
            {"ticker": "000001", "company_name": "동명이인"},
            {"ticker": "000002", "company_name": "동명이인"},
        ])
        with self.assertRaisesRegex(ValueError, "종목코드를 입력"):
            repository.resolve("", "동명이인")

    def test_extracts_db_volume_and_three_day_market_context(self):
        dates = pd.bdate_range("2024-01-01", periods=500)
        history = pd.DataFrame({
            "trade_date": dates, "open": range(1000, 1500), "high": range(1001, 1501),
            "low": range(999, 1499), "close": range(1000, 1500), "volume": [100] * 500,
        })
        service = ChartPatternFeatureService()
        features, reference = service.extract(history, dates[-30].date(), dates[-1].date())
        self.assertEqual(features["volume_source"], "Stock PostgreSQL")
        self.assertEqual(features["db_volume_total"], 3000)
        self.assertEqual(reference, dates[-1].date())

        index = pd.DataFrame({
            "index_code": ["1001"] * 4 + ["2001"] * 4,
            "trade_date": list(pd.bdate_range("2026-10-12", periods=4)) * 2,
            "close_price": [100, 102, 99, 101, 200, 198, 194, 196],
        })
        context = service.market_features(index)
        self.assertEqual(set(context), {"KOSPI", "KOSDAQ"})
        self.assertTrue(all(value["observations"] == 3 for value in context.values()))


if __name__ == "__main__":
    unittest.main()
