from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from pandas import DataFrame


@dataclass(frozen=True)
class ScreenDataset:
    screen_type: str
    title: str
    run: dict[str, Any]
    rows: DataFrame
    latest_price_date: dt.date | None
    latest_indicator_date: dt.date | None


@dataclass(frozen=True)
class ChartDataset:
    ticker: str
    name: str
    market: str
    industry: str
    daily: DataFrame
    weekly: DataFrame
    monthly: DataFrame = field(default_factory=DataFrame)
    quarterly: DataFrame = field(default_factory=DataFrame)
    yearly: DataFrame = field(default_factory=DataFrame)
    investor: dict[str, DataFrame] = field(default_factory=dict)
    loaded_timeframes: frozenset[str] = field(default_factory=frozenset)
    investor_loaded: bool = False

    def bars(self, timeframe: str) -> DataFrame:
        key = str(timeframe).strip().upper()
        frames = {
            "D": self.daily, "W": self.weekly, "M": self.monthly,
            "Q": self.quarterly, "Y": self.yearly,
        }
        try:
            return frames[key]
        except KeyError as error:
            raise ValueError(f"지원하지 않는 봉 주기: {timeframe!r}") from error

    def investor_flow(self, timeframe: str) -> DataFrame:
        return self.investor.get(str(timeframe).strip().upper(), DataFrame()).copy()
