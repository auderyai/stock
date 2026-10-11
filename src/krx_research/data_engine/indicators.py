from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .timeframes import Timeframe, normalize_ohlcv


@dataclass(frozen=True, slots=True)
class IndicatorOptions:
    ema_periods: tuple[int, ...] = (5, 10, 15, 33, 56, 112, 224, 448)
    sma_periods: tuple[int, ...] = (5, 20, 60, 120)
    volume_ma_periods: tuple[int, ...] = (5, 20, 60)
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    rsi_period: int = 14
    rsi_signal_period: int = 9
    stochastic_period: int = 5
    stochastic_smooth_k: int = 3
    stochastic_smooth_d: int = 3
    atr_period: int = 14
    adx_period: int = 14
    roc_period: int = 20

    def validate(self) -> None:
        periods: Iterable[int] = (
            *self.ema_periods,
            *self.sma_periods,
            *self.volume_ma_periods,
            self.bollinger_period,
            self.rsi_period,
            self.rsi_signal_period,
            self.stochastic_period,
            self.stochastic_smooth_k,
            self.stochastic_smooth_d,
            self.atr_period,
            self.adx_period,
            self.roc_period,
        )
        if any(period < 1 for period in periods):
            raise ValueError("보조지표 기간은 모두 1 이상이어야 합니다.")
        if self.bollinger_std <= 0:
            raise ValueError("bollinger_std는 0보다 커야 합니다.")


def _wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain.div(average_loss.replace(0, np.nan))
    rsi = 100 - 100 / (1 + relative_strength)
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
    return rsi.mask((average_loss == 0) & (average_gain == 0), 50.0)


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close_price"].shift(1)
    ranges = pd.concat(
        [
            frame["high_price"] - frame["low_price"],
            (frame["high_price"] - previous_close).abs(),
            (frame["low_price"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _adx(frame: pd.DataFrame, period: int, atr: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    up_move = frame["high_price"].diff()
    down_move = -frame["low_price"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().div(atr.replace(0, np.nan))
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().div(atr.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs().div((plus_di + minus_di).replace(0, np.nan))
    return plus_di, minus_di, dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume.fillna(0)).cumsum()


def calculate_indicators(
    frame: pd.DataFrame,
    timeframe: Timeframe | str = Timeframe.DAILY,
    options: IndicatorOptions | None = None,
) -> pd.DataFrame:
    """Calculate indicators in memory; this function never writes to a database."""

    selected_timeframe = Timeframe.parse(timeframe)
    settings = options or IndicatorOptions()
    settings.validate()
    result = normalize_ohlcv(frame)
    if result.empty:
        return result

    close = result["close_price"].astype(float)
    high = result["high_price"].astype(float)
    low = result["low_price"].astype(float)
    volume = result["volume"].fillna(0).astype(float)

    for period in settings.ema_periods:
        result[f"ema_{period}"] = close.ewm(span=period, adjust=False, min_periods=period).mean()
    for period in settings.sma_periods:
        result[f"sma_{period}"] = close.rolling(period, min_periods=period).mean()
    for period in settings.volume_ma_periods:
        result[f"volume_ma_{period}"] = volume.rolling(period, min_periods=period).mean()

    bb_mid = close.rolling(settings.bollinger_period, min_periods=settings.bollinger_period).mean()
    bb_std = close.rolling(settings.bollinger_period, min_periods=settings.bollinger_period).std(ddof=0)
    result["bb_mid"] = bb_mid
    result["bb_upper"] = bb_mid + settings.bollinger_std * bb_std
    result["bb_lower"] = bb_mid - settings.bollinger_std * bb_std
    result["bb_width_pct"] = (result["bb_upper"] - result["bb_lower"]).div(bb_mid.replace(0, np.nan)).mul(100)
    result["bb_percent_b"] = (close - result["bb_lower"]).div((result["bb_upper"] - result["bb_lower"]).replace(0, np.nan))

    macd_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    macd_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    result["macd"] = macd_fast - macd_slow
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False, min_periods=9).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]

    result["rsi_14"] = _wilder_rsi(close, settings.rsi_period)
    result["rsi_signal_9"] = result["rsi_14"].rolling(
        settings.rsi_signal_period, min_periods=settings.rsi_signal_period
    ).mean()

    rolling_low = low.rolling(settings.stochastic_period, min_periods=settings.stochastic_period).min()
    rolling_high = high.rolling(settings.stochastic_period, min_periods=settings.stochastic_period).max()
    fast_k = 100 * (close - rolling_low).div((rolling_high - rolling_low).replace(0, np.nan))
    result["stoch_slow_k"] = fast_k.rolling(
        settings.stochastic_smooth_k, min_periods=settings.stochastic_smooth_k
    ).mean()
    result["stoch_slow_d"] = result["stoch_slow_k"].rolling(
        settings.stochastic_smooth_d, min_periods=settings.stochastic_smooth_d
    ).mean()

    true_range = _true_range(result)
    result["atr_14"] = true_range.ewm(
        alpha=1 / settings.atr_period,
        adjust=False,
        min_periods=settings.atr_period,
    ).mean()
    result["atr_pct"] = result["atr_14"].div(close.replace(0, np.nan)).mul(100)
    plus_di, minus_di, adx = _adx(result, settings.adx_period, result["atr_14"])
    result["plus_di_14"] = plus_di
    result["minus_di_14"] = minus_di
    result["adx_14"] = adx

    result["obv"] = _obv(close, volume)
    result["roc_20"] = close.pct_change(settings.roc_period, fill_method=None).mul(100)

    high_52w_periods = {
        Timeframe.DAILY: 252,
        Timeframe.WEEKLY: 52,
        Timeframe.MONTHLY: 12,
        Timeframe.QUARTERLY: 4,
        Timeframe.YEARLY: 1,
    }[selected_timeframe]
    result["high_52w"] = high.rolling(high_52w_periods, min_periods=high_52w_periods).max()
    result["low_52w"] = low.rolling(high_52w_periods, min_periods=high_52w_periods).min()
    result["distance_from_52w_high_pct"] = close.div(result["high_52w"].replace(0, np.nan)).sub(1).mul(100)

    ordered_emas = [result[f"ema_{period}"] for period in settings.ema_periods]
    bullish = pd.Series(True, index=result.index)
    bearish = pd.Series(True, index=result.index)
    valid = pd.Series(True, index=result.index)
    for left, right in zip(ordered_emas, ordered_emas[1:]):
        bullish &= left > right
        bearish &= left < right
        valid &= left.notna() & right.notna()
    alignment = pd.Series(0, index=result.index, dtype="int8")
    alignment.loc[valid & bullish] = 1
    alignment.loc[valid & bearish] = -1
    result["ema_alignment"] = alignment
    result["close_above_ema5"] = close > result.get("ema_5", np.nan)
    result["bollinger_breakout"] = close > result["bb_upper"]
    result["volume_surge_20"] = volume > result["volume_ma_20"].mul(2)
    return result


def volume_profile(frame: pd.DataFrame, bins: int = 12) -> pd.DataFrame:
    """Approximate volume-at-price from base candles using their typical price."""

    if not 2 <= bins <= 100:
        raise ValueError("bins는 2~100 범위여야 합니다.")
    data = normalize_ohlcv(frame)
    if data.empty:
        return pd.DataFrame(columns=["price_low", "price_high", "volume", "volume_pct", "cumulative_pct"])
    typical_price = (data["high_price"] + data["low_price"] + data["close_price"]) / 3
    low_price = float(data["low_price"].min())
    high_price = float(data["high_price"].max())
    if not np.isfinite(low_price) or not np.isfinite(high_price):
        return pd.DataFrame(columns=["price_low", "price_high", "volume", "volume_pct", "cumulative_pct"])
    if high_price <= low_price:
        high_price = low_price + max(1.0, abs(low_price) * 0.001)
    edges = np.linspace(low_price, high_price, bins + 1)
    bucket = pd.cut(typical_price, bins=edges, include_lowest=True, labels=False)
    grouped = data.assign(_bucket=bucket).groupby("_bucket", observed=False)["volume"].sum()
    grouped = grouped.reindex(range(bins), fill_value=0).astype(float)
    total = grouped.sum()
    output = pd.DataFrame(
        {
            "price_low": edges[:-1],
            "price_high": edges[1:],
            "volume": grouped.to_numpy(),
        }
    )
    output["volume_pct"] = output["volume"].div(total).mul(100) if total else 0.0
    output = output.sort_values("price_low", ascending=False, ignore_index=True)
    output["cumulative_pct"] = output["volume_pct"].cumsum()
    return output
