import dataclasses
import unittest

import pandas as pd

from krx_research.analytics.technical_indicators import calculate_technical_indicators
from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY


class ChartAnalysisPolicyTests(unittest.TestCase):
    def test_user_approved_settings_are_fixed(self):
        policy = DEFAULT_CHART_ANALYSIS_POLICY
        self.assertEqual(policy.rsi.periods, (14, 9))
        self.assertEqual(policy.macd_oscillator.periods, (12, 26, 9))
        self.assertEqual(policy.stochastic_slow.periods, (5, 3, 3))
        self.assertEqual(policy.moving_average_periods, (5, 10, 15, 33, 56, 112, 224, 448))
        self.assertEqual((policy.bollinger.period, policy.bollinger.deviations,
                          policy.bollinger.center), (20, 2.0, "EMA"))
        self.assertEqual(policy.market_context.volatility_days, 3)
        self.assertEqual(policy.volume_source, "Stock PostgreSQL")

    def test_policy_is_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            DEFAULT_CHART_ANALYSIS_POLICY.volume_source = "image"

    def test_weekly_bollinger_center_uses_policy_ema(self):
        dates = pd.bdate_range("2025-01-01", periods=180)
        close = pd.Series(range(1000, 1180), dtype="float64")
        frame = pd.DataFrame({
            "trade_date": dates, "ticker": "003160", "open": close,
            "high": close + 1, "low": close - 1, "close": close, "volume": 100,
        })
        weekly = calculate_technical_indicators(frame, ticker="003160").weekly
        expected = weekly["close"].ewm(span=20, adjust=False, min_periods=20).mean()
        pd.testing.assert_series_equal(weekly["bb_mid_20"], expected, check_names=False)


if __name__ == "__main__":
    unittest.main()
