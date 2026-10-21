"""Chart-frame transformations independent of storage and UI frameworks."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics.indicators import calculate_indicators
from krx_research.analytics.timeframes import resample_ohlcv
from krx_research.models.workstation import ChartDataset


def build_chart_frame(raw: DataFrame, timeframe: str) -> DataFrame:
    bars = resample_ohlcv(raw, timeframe)
    calculated = calculate_indicators(bars, timeframe)
    frame = calculated.rename(columns={
        "open_price": "open", "high_price": "high", "low_price": "low",
        "close_price": "close", "bb_upper": "bb_upper_20_2",
        "bb_lower": "bb_lower_20_2", "macd_hist": "macd_oscillator",
    }).copy()
    frame["previous_volume"] = frame["volume"].shift(1)
    frame["volume_color"] = np.select(
        [frame["volume"].gt(frame["previous_volume"]),
         frame["volume"].lt(frame["previous_volume"])],
        ["#d62728", "#1f77b4"], default="#808080",
    )
    return frame


def select_chart_window(
    dataset: ChartDataset, trading_days: int | None
) -> tuple[DataFrame, DataFrame]:
    if trading_days is not None and trading_days < 1:
        raise ValueError("거래일수는 1 이상이어야 합니다.")
    daily = dataset.daily if trading_days is None else dataset.daily.tail(trading_days)
    if daily.empty:
        raise ValueError(f"{dataset.ticker}의 표시 가능한 일봉이 없습니다.")
    if trading_days is None:
        return daily.copy(), dataset.weekly.copy()
    visible = daily.assign(
        trade_date=daily.index,
        week_end=daily.index.to_period("W-FRI").end_time.normalize(),
    )
    weekly = visible.groupby("week_end", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
        trading_days=("close", "size"), last_trade_date=("trade_date", "max"),
    )
    weekly.index = pd.DatetimeIndex(weekly.index, name="week_end")
    weekly.insert(0, "ticker", dataset.ticker)
    extra = [column for column in dataset.weekly.columns if column not in weekly.columns]
    return daily.copy(), weekly.join(dataset.weekly[extra], how="left").copy()


def calculate_volume_profile(
    frame: DataFrame, *, bins: int = 15
) -> tuple[np.ndarray, np.ndarray, float]:
    if bins < 1:
        raise ValueError("bins must be at least 1")
    if frame.empty:
        return np.array([]), np.array([]), 0.0
    lower, upper = float(frame["low"].min()), float(frame["high"].max())
    if not np.isfinite(lower) or not np.isfinite(upper):
        raise ValueError("가격 범위에 유효하지 않은 값이 있습니다.")
    if upper <= lower:
        upper = lower + max(abs(lower) * 0.01, 1.0)
    edges = np.linspace(lower, upper, bins + 1)
    lows, highs = frame["low"].to_numpy(float), frame["high"].to_numpy(float)
    closes = frame["close"].to_numpy(float)
    candle_volume = frame["volume"].to_numpy(float)
    if not np.isfinite(candle_volume).all() or (candle_volume < 0).any():
        raise ValueError("거래량에 유효하지 않은 값이 있습니다.")
    overlap = np.clip(
        np.minimum(highs[:, None], edges[None, 1:])
        - np.maximum(lows[:, None], edges[None, :-1]),
        0.0,
        None,
    )
    totals = overlap.sum(axis=1)
    weights = np.divide(
        overlap, totals[:, None], out=np.zeros_like(overlap),
        where=totals[:, None] > 0,
    )
    volume = (weights * candle_volume[:, None]).sum(axis=0)
    points = totals <= 0
    if points.any():
        buckets = np.clip(np.digitize(closes[points], edges) - 1, 0, bins - 1)
        np.add.at(volume, buckets, candle_volume[points])
    return (
        (edges[:-1] + edges[1:]) / 2.0,
        volume,
        float(edges[1] - edges[0]) * 0.84,
    )
