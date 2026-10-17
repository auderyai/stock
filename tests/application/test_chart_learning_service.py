from datetime import date
import unittest

import pandas as pd

from krx_research.chart_learning.service import ChartPatternFeatureService


class ChartPatternFeatureServiceTests(unittest.TestCase):
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
