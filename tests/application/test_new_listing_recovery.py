from __future__ import annotations

import unittest

import pandas as pd

from krx_research.application.new_listing_recovery import NewListingRecoveryService


def _bars(dates: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame({
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "volume": 10,
        "amount": 20,
        "ticker": "179880",
        "source": "test",
    }, index=pd.to_datetime(dates))
    frame.index.name = "trade_date"
    return frame


class _Repository:
    def __init__(self, stored: pd.DataFrame) -> None:
        self.stored = stored

    def get_ohlcv(self, _ticker, start, end):
        return self.stored.loc[str(start):str(end)].copy()

    def upsert_ohlcv(self, frame):
        self.stored = pd.concat([self.stored, frame]).loc[
            lambda value: ~value.index.duplicated(keep="last")
        ].sort_index()
        return len(frame)


class NewListingRecoveryTests(unittest.TestCase):
    MASTER = pd.DataFrame([{
        "ticker": "179880",
        "name": "멜콘",
        "market": "KOSDAQ",
        "listing_date": "20261015",
    }])

    def test_recovers_only_missing_listing_history(self) -> None:
        repository = _Repository(_bars(["2026-10-28"]))
        fetched = _bars(["2026-10-15", "2026-10-16", "2026-10-28"])

        report = NewListingRecoveryService(repository, lambda *_: fetched).recover(
            self.MASTER,
            "2026-01-01",
            "2026-10-28",
            apply=True,
        )

        self.assertEqual("completed", report["status"])
        self.assertEqual(2, report["missing_rows"])
        self.assertEqual(2, report["rows_written"])
        self.assertEqual(3, len(repository.stored))

    def test_dry_run_does_not_write(self) -> None:
        repository = _Repository(_bars(["2026-10-28"]))

        report = NewListingRecoveryService(repository, lambda *_: _bars([
            "2026-10-15", "2026-10-28"
        ])).recover(self.MASTER, "2026-01-01", "2026-10-28")

        self.assertEqual(1, report["missing_rows"])
        self.assertEqual(0, report["rows_written"])
        self.assertEqual(1, len(repository.stored))


if __name__ == "__main__":
    unittest.main()
