from __future__ import annotations

from typing import Any

import pandas as pd

from krx_research.ui.data import REALTIME_SOURCE_MODE, WorkstationData
from krx_research_nextgen.models.screening import ScreeningKind, ScreeningQuery, ScreeningResult


_SCREEN_KEYS = {
    (ScreeningKind.EMA_SIMILARITY, "ALL"): "ema_similarity",
    (ScreeningKind.HIGH_52W, "ALL"): "high_52w",
    (ScreeningKind.NEAR_HIGH_52W, "ALL"): "near_high_52w",
    (ScreeningKind.BOLLINGER_BREAKOUT, "ALL"): "bollinger_breakout",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI"): "kospi_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSDAQ"): "kosdaq_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI+KOSDAQ"): "weekly_return",
    (ScreeningKind.DAILY_GAINERS, "KOSPI200"): "kospi200_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSDAQ150"): "kosdaq150_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSPI200+KOSDAQ150"): "kospi200_kosdaq150_daily_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI200"): "kospi200_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSDAQ150"): "kosdaq150_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI200+KOSDAQ150"): "kospi200_kosdaq150_weekly_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSPI"): "kospi_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSDAQ"): "kosdaq_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSPI+KOSDAQ"): "kospi_kosdaq_daily_gainers",
    (ScreeningKind.TURNOVER_TOP, "KOSPI+KOSDAQ"): "kospi_kosdaq_daily_trading_value",
    (ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSPI"): "kospi_weekly_trading_value",
    (ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSDAQ"): "kosdaq_weekly_trading_value",
    (ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSPI+KOSDAQ"): "kospi_kosdaq_weekly_trading_value",
}


class RealtimeScreeningRepository:
    """Adapts the established validated live-quote pipeline to NextGen results."""

    def __init__(self, data: WorkstationData) -> None:
        self._data = data

    def run(self, query: ScreeningQuery) -> list[ScreeningResult]:
        key = _SCREEN_KEYS.get((query.kind, query.market)) or _SCREEN_KEYS.get((query.kind, "ALL"))
        if key is None:
            raise ValueError(f"{query.kind.value}은 실시간 조회를 지원하지 않습니다. 데이터베이스를 선택하십시오.")
        if key == "ema_similarity":
            raise ValueError("이동평균 유사배열은 과거 구간 계산이 필요하므로 데이터베이스를 선택하십시오.")
        dataset = self._data.load_screen(
            key, data_source_mode=REALTIME_SOURCE_MODE,
            quote_venue=self._venue(query.quote_venue), comparison_ticker=query.comparison_ticker,
        )
        rows = dataset.rows.copy()
        if query.kind is ScreeningKind.NEAR_HIGH_52W:
            distance = pd.to_numeric(rows.get("distance_from_52w_high_pct"), errors="coerce")
            rows = rows.loc[distance.between(query.near_low, query.near_high, inclusive="both")]
        if rows.empty:
            raise ValueError("실시간 시세는 수집되었지만 선택 조건에 맞는 종목이 0건입니다.")
        return [self._convert(row, dataset.run, rank) for rank, (_, row) in enumerate(rows.head(query.limit).iterrows(), 1)]

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
