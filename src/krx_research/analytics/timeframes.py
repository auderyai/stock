from __future__ import annotations

from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class Timeframe(str, Enum):
    DAILY = "D"
    WEEKLY = "W"
    MONTHLY = "M"
    QUARTERLY = "Q"
    YEARLY = "Y"

    @classmethod
    def parse(cls, value: "Timeframe | str") -> "Timeframe":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().upper()
        aliases = {
            "D": cls.DAILY,
            "DAY": cls.DAILY,
            "DAILY": cls.DAILY,
            "일": cls.DAILY,
            "일봉": cls.DAILY,
            "W": cls.WEEKLY,
            "WEEK": cls.WEEKLY,
            "WEEKLY": cls.WEEKLY,
            "주": cls.WEEKLY,
            "주봉": cls.WEEKLY,
            "M": cls.MONTHLY,
            "MONTH": cls.MONTHLY,
            "MONTHLY": cls.MONTHLY,
            "월": cls.MONTHLY,
            "월봉": cls.MONTHLY,
            "Q": cls.QUARTERLY,
            "QUARTER": cls.QUARTERLY,
            "QUARTERLY": cls.QUARTERLY,
            "분기": cls.QUARTERLY,
            "분기봉": cls.QUARTERLY,
            "Y": cls.YEARLY,
            "YEAR": cls.YEARLY,
            "YEARLY": cls.YEARLY,
            "연": cls.YEARLY,
            "년": cls.YEARLY,
            "년봉": cls.YEARLY,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ValueError(f"지원하지 않는 봉 주기: {value!r}") from exc


CANONICAL_COLUMNS = (
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "amount",
)

_COLUMN_ALIASES = {
    "open": "open_price",
    "high": "high_price",
    "low": "low_price",
    "close": "close_price",
    "value": "amount",
    "trade_value": "amount",
    "시가": "open_price",
    "고가": "high_price",
    "저가": "low_price",
    "종가": "close_price",
    "거래량": "volume",
    "거래대금": "amount",
    "날짜": "trade_date",
    "date": "trade_date",
}


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize DB/provider OHLCV columns and enforce an ascending DatetimeIndex."""

    if frame is None or frame.empty:
        return pd.DataFrame(columns=[*CANONICAL_COLUMNS, "change_rate"], index=pd.DatetimeIndex([], name="trade_date"))
    result = frame.copy()
    result = result.rename(columns={column: _COLUMN_ALIASES.get(str(column), str(column)) for column in result.columns})
    if "trade_date" in result.columns:
        result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
        result = result.set_index("trade_date")
    else:
        result.index = pd.to_datetime(result.index, errors="coerce")
        result.index.name = "trade_date"
    result = result.loc[~result.index.isna()].sort_index()
    if "stock_code" in result.columns:
        row_keys = pd.MultiIndex.from_arrays(
            [result["stock_code"].astype(str), result.index],
            names=["stock_code", "trade_date"],
        )
        result = result.loc[~row_keys.duplicated(keep="last")]
    else:
        result = result.loc[~result.index.duplicated(keep="last")]
    for column in CANONICAL_COLUMNS:
        if column not in result.columns:
            result[column] = 0 if column in ("volume", "amount") else np.nan
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "change_rate" in result.columns:
        result["change_rate"] = pd.to_numeric(result["change_rate"], errors="coerce")
    return result


def _period_key(index: pd.DatetimeIndex, timeframe: Timeframe) -> pd.PeriodIndex:
    if timeframe is Timeframe.WEEKLY:
        return index.to_period("W-FRI")
    if timeframe is Timeframe.MONTHLY:
        return index.to_period("M")
    if timeframe is Timeframe.QUARTERLY:
        return index.to_period("Q-DEC")
    if timeframe is Timeframe.YEARLY:
        return index.to_period("Y-DEC")
    raise ValueError("일봉에는 기간 키가 필요하지 않습니다.")


def resample_ohlcv(frame: pd.DataFrame, timeframe: Timeframe | str) -> pd.DataFrame:
    """Build D/W/M/Q/Y candles from daily rows without persisting derived bars."""

    period = Timeframe.parse(timeframe)
    daily = normalize_ohlcv(frame)
    if daily.empty:
        return daily
    if period is Timeframe.DAILY:
        result = daily.copy()
        if "change_rate" not in result:
            result["change_rate"] = result["close_price"].pct_change(fill_method=None).mul(100)
        return result

    working = daily.assign(_trade_date=daily.index, _period=_period_key(daily.index, period))
    aggregation: dict[str, Any] = {
        "_trade_date": "max",
        "open_price": "first",
        "high_price": "max",
        "low_price": "min",
        "close_price": "last",
        "volume": "sum",
        "amount": "sum",
    }
    result = working.groupby("_period", sort=True, observed=True).agg(aggregation)
    result = result.set_index("_trade_date")
    result.index.name = "trade_date"
    result["change_rate"] = result["close_price"].pct_change(fill_method=None).mul(100)
    return result
