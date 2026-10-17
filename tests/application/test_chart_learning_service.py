from datetime import date
import unittest

import pandas as pd

from krx_research.chart_learning.repository import ChartLearningRepository
from krx_research.chart_learning.service import ChartLearningService, ChartPatternFeatureService


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
    def test_database_sample_identity_is_stable_without_an_image(self):
        values = "232140", date(2025, 4, 3), date(2026, 10, 16)
        first = ChartLearningService._database_digest(*values)
        second = ChartLearningService._database_digest(*values)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

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

    def test_extracts_db_volume_and_statistical_market_context(self):
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

        index_dates = dates[-320:]
        index = pd.DataFrame({
            "index_code": ["1001"] * 320 + ["2001"] * 320,
            "trade_date": list(index_dates) * 2,
            "close_price": list(range(2000, 2320)) + list(range(1000, 1320)),
        })
        context = service.market_features(
            index, history, dates[-30].date(), dates[-1].date()
        )
        self.assertEqual(set(context), {"KOSPI", "KOSDAQ"})
        self.assertTrue(all(set(value["recent_return_pct"]) == {"3", "20", "60", "252"}
                            for value in context.values()))
        self.assertTrue(all("stock_beta" in value for value in context.values()))
        self.assertTrue(all("stock_excess_return_pct" in value for value in context.values()))


if __name__ == "__main__":
    unittest.main()
