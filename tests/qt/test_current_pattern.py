from datetime import date
import unittest

import numpy as np
import pandas as pd

from krx_research.qt.services.current_pattern import (
    CupWithHandleDetector, CurrentPatternKind, CurrentPatternQuery, DoubleBottomDetector,
    MarketContextAnalyzer, PatternStage,
)


def frame(values: list[float]) -> pd.DataFrame:
    count = len(values)
    return pd.DataFrame({
        "stock_code": ["000001"] * count,
        "stock_name": ["검증종목"] * count,
        "trade_date": pd.bdate_range(end="2026-10-16", periods=count),
        "close": values,
        "high": np.asarray(values) * 1.01,
        "low": np.asarray(values) * 0.99,
        "volume": np.linspace(100_000, 200_000, count),
    })


def path(*segments: tuple[float, float, int]) -> list[float]:
    values: list[float] = []
    for start, end, count in segments:
        values.extend(np.linspace(start, end, count, endpoint=False).tolist())
    values.append(segments[-1][1])
    return values


class DoubleBottomDetectorTests(unittest.TestCase):
    def test_query_rejects_invalid_result_count(self):
        with self.assertRaises(ValueError):
            CurrentPatternQuery(CurrentPatternKind.DOUBLE_BOTTOM, 0)

    def test_second_bottom_complete_waiting_for_neckline(self):
        values = path((115, 82, 25), (82, 103, 20), (103, 84, 22), (84, 98, 14))
        result = DoubleBottomDetector().detect(frame(values))
        self.assertIsNotNone(result)
        self.assertEqual(result.stage, PatternStage.READY)
        self.assertIn("두 저점 차이", result.evidence)

    def test_recent_breakout_is_kept_but_extended_breakout_is_rejected(self):
        base = path((115, 82, 25), (82, 103, 20), (103, 84, 22), (84, 101, 12))
        confirmed = DoubleBottomDetector().detect(frame(base + [104, 106, 105]))
        extended = DoubleBottomDetector().detect(frame(base + [104, 120, 145]))
        self.assertEqual(confirmed.stage, PatternStage.CONFIRMED)
        self.assertIsNone(extended)


class CupWithHandleDetectorTests(unittest.TestCase):
    def test_handle_recovery_waits_for_breakout(self):
        values = path((100, 102, 12), (102, 72, 28), (72, 99, 32),
                      (99, 91, 8), (91, 97, 7))
        result = CupWithHandleDetector().detect(frame(values))
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, CurrentPatternKind.CUP_WITH_HANDLE)
        self.assertEqual(result.stage, PatternStage.READY)

    def test_failed_handle_is_not_returned(self):
        values = path((100, 102, 12), (102, 72, 28), (72, 99, 32),
                      (99, 91, 8), (91, 60, 7))
        self.assertIsNone(CupWithHandleDetector().detect(frame(values)))


class MarketContextAnalyzerTests(unittest.TestCase):
    def test_reports_market_relative_statistics(self):
        dates = pd.bdate_range(end="2026-10-16", periods=80)
        market = pd.DataFrame({
            "index_code": ["1001"] * 80 + ["2001"] * 80,
            "trade_date": list(dates) * 2,
            "close": list(np.linspace(100, 110, 80)) + list(np.linspace(100, 105, 80)),
        })
        stock = frame(np.linspace(100, 125, 80).tolist())
        result = MarketContextAnalyzer(market).assess(stock, "KOSPI")
        self.assertEqual(result["market_context"], "KOSPI")
        self.assertGreater(result["relative_return_20d_pct"], 0)


if __name__ == "__main__":
    unittest.main()
