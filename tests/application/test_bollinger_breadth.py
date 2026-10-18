from __future__ import annotations

from datetime import date, timedelta
import unittest

import pandas as pd

from krx_research_nextgen.models.screening import ScreeningKind, ScreeningQuery
from krx_research_nextgen.services.bollinger_breadth_service import (
    BollingerBreadthCalculator,
    BollingerBreadthService,
)


def _history(code: str, closes: list[float]) -> list[dict[str, object]]:
    start = date(2026, 1, 1)
    return [{
        "stock_code": code, "stock_name": code, "market": "KOSPI",
        "trade_date": start + timedelta(days=index), "close": close,
        "trading_value": 1_000_000.0,
    } for index, close in enumerate(closes)]


class _Source:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def latest_trade_date(self) -> str:
        return "2026-01-21"

    def bollinger_input(self, *_args, **_kwargs) -> pd.DataFrame:
        return self.frame

    def enrich_display_fields(self, rows):
        return rows


class _Store:
    saved: tuple | None = None

    def save(self, *args) -> None:
        self.saved = args


class BollingerBreadthTests(unittest.TestCase):
    def test_calculator_detects_only_new_close_crosses(self) -> None:
        frame = pd.DataFrame(
            _history("000001", [100.0] * 20 + [130.0])
            + _history("000002", [100.0] * 20 + [70.0])
            + _history("000003", [100.0] * 19 + [130.0, 131.0])
        )
        rows, universe = BollingerBreadthCalculator().calculate(frame, date(2026, 1, 21))

        self.assertEqual(universe, 3)
        self.assertEqual(
            {(row["stock_code"], row["direction"]) for row in rows},
            {("000001", "UPPER"), ("000002", "LOWER")},
        )

    def test_unranked_service_returns_every_match_and_stores_both_directions(self) -> None:
        frame = pd.DataFrame(
            _history("000001", [100.0] * 20 + [130.0])
            + _history("000002", [100.0] * 20 + [140.0])
            + _history("000003", [100.0] * 20 + [70.0])
        )
        store = _Store()
        service = BollingerBreadthService(_Source(frame), store)  # type: ignore[arg-type]

        results = service.run(ScreeningQuery(
            ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT, limit=1, as_of_date="2026-01-21"
        ))

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(store.saved)
        assert store.saved is not None
        self.assertEqual(len(store.saved[1]), 3)
        self.assertEqual(store.saved[2], 3)


if __name__ == "__main__":
    unittest.main()
