from __future__ import annotations

from typing import Any

import pandas as pd

from krx_research.data_engine.workstation_repository import WorkstationData
from krx_research.policies.workstation_options import REALTIME_SOURCE_MODE
from krx_research_nextgen.models.screening import ScreeningQuery, ScreeningResult


class RealtimeScreeningRepository:
    """Adapts the established validated live-quote pipeline to NextGen results."""

    def __init__(self, data: WorkstationData) -> None:
        self._data = data

    def load(self, key: str, query: ScreeningQuery) -> list[ScreeningResult]:
        dataset = self._data.load_screen(
            key, data_source_mode=REALTIME_SOURCE_MODE,
            quote_venue=self._venue(query.quote_venue), comparison_ticker=query.comparison_ticker,
        )
        return [self._convert(row, dataset.run, rank) for rank, (_, row) in enumerate(dataset.rows.iterrows(), 1)]

    @staticmethod
    def _venue(value: str) -> str:
        return "COMBINED" if value == "KRX+NXT" else value

    @staticmethod
    def _number(row: pd.Series, *names: str) -> float | None:
        value: Any = next((row[name] for name in names if name in row and pd.notna(row[name])), None)
        return None if value is None else float(value)

    @classmethod
    def _convert(cls, row: pd.Series, run: dict[str, Any], rank: int) -> ScreeningResult:
        code = str(row.get("ticker", row.get("stock_code", ""))).replace(".0", "").zfill(6)
        trade_date = str(row.get("screen_date") or run.get("as_of_date") or "")[:10]
        return ScreeningResult(
            code, str(row.get("name", row.get("stock_name", ""))), str(row.get("market", "")),
            trade_date, cls._number(row, "close") or 0.0,
            cls._number(row, "daily_return_pct", "change_pct"),
            cls._number(row, "estimated_trading_value", "trading_value"),
            cls._number(row, "high_52w"), cls._number(row, "distance_from_52w_high_pct"), rank,
            str(row.get("industry", "")), cls._number(row, "weekly_return_pct"),
            cls._number(row, "open"), cls._number(row, "high"), cls._number(row, "low"),
            cls._number(row, "volume"), cls._number(row, "market_cap"),
        )
