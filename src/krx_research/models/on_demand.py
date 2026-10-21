"""Immutable results returned by on-demand data access."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from pandas import DataFrame


@dataclass(frozen=True)
class OnDemandScreenResult:
    rows: DataFrame
    as_of_date: dt.date
    universe_count: int


@dataclass(frozen=True)
class OnDemandChartResult:
    ticker: str
    name: str
    market: str
    industry: str
    bars: dict[str, DataFrame]
    investor: dict[str, DataFrame]
