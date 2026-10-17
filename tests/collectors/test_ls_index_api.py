from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

from krx_research.collectors.ls_index_api import LSIndexClient, _frame


class LSIndexFrameTests(unittest.TestCase):
    @patch("krx_research.collectors.ls_index_api.XingBridgeClient")
    def test_enforces_t8429_minimum_request_interval(self, bridge) -> None:
        LSIndexClient(delay=0.2)

        self.assertEqual(1.1, bridge.call_args.kwargs["delay"])

    def test_normalizes_t8429_prices_from_hundredths(self) -> None:
        day = dt.date(2026, 10, 16)
        frame = _frame([{
            "date": "20261016", "open": "565399", "high": "580994",
            "low": "559033", "close": "566805", "jdiff_vol": "123", "value": "456",
        }], day, day)

        self.assertEqual(5668.05, frame.iloc[0]["종가"])
        self.assertEqual(123, frame.iloc[0]["거래량"])
        self.assertEqual(456.0, frame.iloc[0]["LS거래대금원시"])


if __name__ == "__main__":
    unittest.main()
