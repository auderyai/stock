from __future__ import annotations

from datetime import date
from typing import Any, Protocol, Sequence

import pandas as pd

from .cache import TTLCache
from krx_research.analytics.indicators import IndicatorOptions, calculate_indicators, volume_profile
from krx_research.analytics.investor import aggregate_investor_flow, normalize_investor_code, pivot_net_flow
from krx_research.analytics.timeframes import Timeframe, resample_ohlcv


class ReadRepository(Protocol):
    def latest_ohlcv_date(self, ticker: str | None = None) -> date | None: ...

    def latest_investor_date(self, ticker: str | None = None) -> date | None: ...

    def get_ohlcv(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        limit: int | None = None,
    ) -> pd.DataFrame: ...

    def get_investor_flow(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        investor_types: Sequence[str] | None = None,
    ) -> pd.DataFrame: ...


def _date_key(value: date | str | None) -> str | None:
    return None if value is None else pd.Timestamp(value).date().isoformat()


class MarketDataService:
    """Read raw daily facts and calculate every requested representation in RAM."""

    def __init__(
        self,
        repository: ReadRepository,
        *,
        cache_size: int = 128,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self.repository = repository
        self.cache: TTLCache[pd.DataFrame] = TTLCache(cache_size, cache_ttl_seconds)

    def clear_cache(self) -> None:
        self.cache.clear()

    def get_bars(
        self,
        ticker: str,
        timeframe: Timeframe | str = Timeframe.DAILY,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        limit: int | None = None,
        indicators: bool = False,
        indicator_options: IndicatorOptions | None = None,
    ) -> pd.DataFrame:
        selected = Timeframe.parse(timeframe)
        if start is not None and end is not None and pd.Timestamp(start) > pd.Timestamp(end):
            raise ValueError("start는 end보다 늦을 수 없습니다.")
        if limit is not None and limit < 1:
            raise ValueError("limit는 1 이상이어야 합니다.")
        ticker = str(ticker).zfill(6)
        generation = self.repository.latest_ohlcv_date(ticker)
        option_key = indicator_options or IndicatorOptions()
        key = (
            "bars",
            ticker,
            selected.value,
            _date_key(start),
            _date_key(end),
            limit,
            indicators,
            option_key,
            generation,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        # A KRX listing has only several thousand daily rows. Loading a single ticker's
        # full history keeps EMA-448 and yearly calculations correct while staying cheap.
        raw = self.repository.get_ohlcv(ticker, end=end)
        result = resample_ohlcv(raw, selected)
        if indicators:
            result = calculate_indicators(result, selected, option_key)
        if start is not None:
            result = result.loc[result.index >= pd.Timestamp(start)]
        if end is not None:
            result = result.loc[result.index <= pd.Timestamp(end)]
        if limit is not None:
            result = result.tail(limit)
        self.cache.set(key, result)
        return result.copy(deep=True)

    def get_indicators(
        self,
        ticker: str,
        timeframe: Timeframe | str = Timeframe.DAILY,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        limit: int | None = None,
        options: IndicatorOptions | None = None,
    ) -> pd.DataFrame:
        return self.get_bars(
            ticker,
            timeframe,
            start,
            end,
            limit=limit,
            indicators=True,
            indicator_options=options,
        )

    def get_investor_flow(
        self,
        ticker: str,
        timeframe: Timeframe | str = Timeframe.DAILY,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        investor_types: Sequence[str] | None = None,
        include_totals: bool = True,
        pivot: bool = False,
        unit: str = "value",
    ) -> pd.DataFrame:
        selected = Timeframe.parse(timeframe)
        ticker = str(ticker).zfill(6)
        generation_method = getattr(self.repository, "latest_investor_date", None)
        generation = generation_method(ticker) if callable(generation_method) else None
        key = (
            "investor",
            ticker,
            selected.value,
            _date_key(start),
            _date_key(end),
            tuple(investor_types or ()),
            include_totals,
            pivot,
            unit,
            generation,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        raw = self.repository.get_investor_flow(ticker, start, end, investor_types)
        result = aggregate_investor_flow(raw, selected, include_totals=include_totals)
        if investor_types:
            requested_codes = {normalize_investor_code(value) for value in investor_types}
            result = result.loc[result["investor_type"].isin(requested_codes)].copy()
        if pivot:
            result = pivot_net_flow(result, unit)
        self.cache.set(key, result)
        return result.copy(deep=True)

    def get_volume_profile(
        self,
        ticker: str,
        timeframe: Timeframe | str = Timeframe.DAILY,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        bins: int = 12,
    ) -> pd.DataFrame:
        return volume_profile(self.get_bars(ticker, timeframe, start, end), bins=bins)

    def latest_snapshot(self, ticker: str, timeframe: Timeframe | str = "D") -> dict[str, Any] | None:
        data = self.get_indicators(ticker, timeframe, limit=1)
        if data.empty:
            return None
        row = data.iloc[-1].to_dict()
        row["trade_date"] = data.index[-1].date()
        row["stock_code"] = str(ticker).zfill(6)
        row["timeframe"] = Timeframe.parse(timeframe).value
        return row
