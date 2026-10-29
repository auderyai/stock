from __future__ import annotations

import time
import unittest

import pandas as pd

from krx_research.collectors.bounded_market_data import BoundedOhlcvFetcher
from krx_research.collectors.market_data import MarketDataError


def _frame(*_args) -> pd.DataFrame:
    return pd.DataFrame({"close": [1]})


def _wait(*_args) -> pd.DataFrame:
    time.sleep(2)
    return _frame()


class BoundedOhlcvFetcherTests(unittest.TestCase):
    def test_returns_existing_collector_result(self) -> None:
        with BoundedOhlcvFetcher(_frame, timeout_seconds=5) as fetcher:
            result = fetcher("000000", 1, 2)
        self.assertEqual(1, result.at[0, "close"])

    def test_terminates_stalled_collector(self) -> None:
        started = time.monotonic()
        with BoundedOhlcvFetcher(_wait, timeout_seconds=0.1) as fetcher:
            with self.assertRaisesRegex(MarketDataError, "provider timeout"):
                fetcher("000000", 1, 2)
        self.assertLess(time.monotonic() - started, 1.8)


if __name__ == "__main__":
    unittest.main()
