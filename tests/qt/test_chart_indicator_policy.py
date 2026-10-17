import unittest

import numpy as np
import pandas as pd

from krx_research_nextgen.models.chart_data import IndicatorConfig
from krx_research_nextgen.services.technical_analysis_service import TechnicalAnalysisService


class ChartIndicatorPolicyTests(unittest.TestCase):
    def test_ema_smoothing_policy_is_applied(self):
        close = pd.Series(100.0 + np.linspace(0.0, 20.0, 80) + np.sin(np.arange(80)) * 3)
        frame = pd.DataFrame({
            "open": close, "high": close + 2, "low": close - 2,
            "close": close, "volume": np.arange(80) + 100,
        })
        result = TechnicalAnalysisService().enrich(frame, IndicatorConfig())
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(span=14, adjust=False, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False, min_periods=14).mean()
        expected_rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        expected_bb = close.ewm(span=20, adjust=False, min_periods=20).mean()
        expected_rsi_signal = result["rsi"].ewm(span=9, adjust=False, min_periods=9).mean()
        pd.testing.assert_series_equal(result["rsi"], expected_rsi, check_names=False)
        pd.testing.assert_series_equal(result["bb_mid"], expected_bb, check_names=False)
        pd.testing.assert_series_equal(result["rsi_signal"], expected_rsi_signal,
                                       check_names=False)


if __name__ == "__main__":
    unittest.main()
