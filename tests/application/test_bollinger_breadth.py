from __future__ import annotations

from datetime import date, timedelta
import unittest

import pandas as pd

from krx_research_nextgen.models.screening import ScreeningKind, ScreeningQuery
from krx_research_nextgen.models.screen_catalog import SCREENS
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
        self.universe = None

    def latest_trade_date(self) -> str:
        return "2026-01-21"

    def bollinger_input(self, *_args, **kwargs) -> pd.DataFrame:
        self.universe = kwargs.get("universe")
        return self.frame

    def enrich_display_fields(self, rows):
        return rows


class _Store:
    saved: tuple | None = None

    def save(self, *args) -> None:
        self.saved = args


class BollingerBreadthTests(unittest.TestCase):
    def test_all_bollinger_screens_allow_the_common_universe_checkbox(self) -> None:
        kinds = {
            ScreeningKind.BOLLINGER_BREAKOUT,
            ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT,
            ScreeningKind.DAILY_BOLLINGER_LOWER_BREAKOUT,
        }

        self.assertEqual(
            {spec.market for spec in SCREENS if spec.kind in kinds},
            {"ALL"},
        )

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

    def test_interactive_screen_uses_query_universe_without_overwriting_history(self) -> None:
        frame = pd.DataFrame(
            _history("000001", [100.0] * 20 + [130.0])
            + _history("000002", [100.0] * 20 + [140.0])
            + _history("000003", [100.0] * 20 + [70.0])
        )
        store = _Store()
        source = _Source(frame)
        service = BollingerBreadthService(source, store)  # type: ignore[arg-type]

        results = service.run(ScreeningQuery(
            ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT,
            limit=1,
            market="ALL",
            as_of_date="2026-01-21",
        ))

        self.assertEqual(len(results), 2)
        self.assertIsNone(store.saved)
        self.assertEqual(source.universe, "ALL")

    def test_daily_refresh_persists_the_canonical_core_index_snapshot(self) -> None:
        frame = pd.DataFrame(_history("000001", [100.0] * 20 + [130.0]))
        store = _Store()
        source = _Source(frame)

        BollingerBreadthService(source, store).refresh(date(2026, 1, 21))  # type: ignore[arg-type]

        self.assertIsNotNone(store.saved)
        assert store.saved is not None
        self.assertEqual(len(store.saved[1]), 1)
        self.assertEqual(store.saved[2], 1)
        self.assertEqual(source.universe, "KOSPI200+KOSDAQ150")

    def test_weekly_breakout_uses_current_date_and_ema_center(self) -> None:
        start = date(2026, 5, 29)
        current_date = start + timedelta(days=7 * 19)
        rows = [
            {
                "stock_code": "000001", "stock_name": "current", "market": "KOSPI",
                "trade_date": start + timedelta(days=7 * index),
                "close": 130.0 if index == 19 else 100.0,
                "trading_value": 1_000_000.0,
            }
            for index in range(20)
        ]
        rows.extend(
            {
                "stock_code": "000002", "stock_name": "stale", "market": "KOSDAQ",
                "trade_date": start + timedelta(days=7 * index),
                "close": 130.0 if index == 18 else 100.0,
                "trading_value": 1_000_000.0,
            }
            for index in range(19)
        )

        selected = BollingerBreadthCalculator().weekly(
            pd.DataFrame(rows), current_date
        )

        self.assertEqual([row["stock_code"] for row in selected], ["000001"])
        self.assertGreater(float(selected[0]["middle"]), 100.0)


if __name__ == "__main__":
    unittest.main()
