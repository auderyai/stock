from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class TrendAssessment:
    accepted: bool
    return_pct: float
    slope_pct: float
    range_position_pct: float


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    accepted: bool
    maximum_gap_pct: float
    unchanged_pct: float
    zero_volume_pct: float
    maximum_drawdown_pct: float
    history_range_position_pct: float


@dataclass(frozen=True, slots=True)
class RisingWaveAssessment:
    accepted: bool
    gain_pct: float
    trading_days: int


@dataclass(frozen=True, slots=True)
class LongTermTrendAssessment:
    accepted: bool
    close_over_ma60_pct: float
    close_over_ma120_pct: float
    ma60_over_ma120_pct: float
    ma120_change_pct: float


class UptrendPolicy:
    """Admits only rising patterns that finish in the upper price range."""

    def __init__(self, minimum_range_position: float = 60.0):
        self.minimum_range_position = float(minimum_range_position)

    def assess(self, frame: pd.DataFrame, start: date | None = None,
               end: date | None = None) -> TrendAssessment:
        data = frame.sort_values("trade_date").drop_duplicates("trade_date")
        if start is not None:
            data = data.loc[data.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))]
        close = pd.to_numeric(data.close, errors="coerce").dropna().to_numpy(dtype=float)
        if len(close) < 2 or close[0] <= 0:
            return TrendAssessment(False, float("nan"), float("nan"), float("nan"))
        low, high = float(close.min()), float(close.max())
        return_pct = (close[-1] / close[0] - 1.0) * 100.0
        slope_pct = float(np.polyfit(np.arange(len(close)), close / close[0] - 1.0, 1)[0] * 100)
        range_position = 0.0 if high == low else (close[-1] - low) / (high - low) * 100.0
        accepted = return_pct > 0 and slope_pct > 0 and range_position >= self.minimum_range_position
        return TrendAssessment(accepted, return_pct, slope_pct, range_position)


class PatternQualityPolicy:
    """Rejects discontinuous, inactive and long-term bottom-bound price histories."""

    def assess(self, frame: pd.DataFrame) -> QualityAssessment:
        data = frame.sort_values("trade_date").drop_duplicates("trade_date")
        close = pd.to_numeric(data.close, errors="coerce").dropna()
        volume = pd.to_numeric(data.loc[close.index, "volume"], errors="coerce").fillna(0)
        if len(close) < 2 or close.iloc[0] <= 0:
            return QualityAssessment(False, *(float("nan"),) * 5)
        returns = close.pct_change()
        low, high, latest = float(close.min()), float(close.max()), float(close.iloc[-1])
        gap = float(returns.abs().max() * 100)
        unchanged = float(returns.eq(0).mean() * 100)
        zero_volume = float(volume.le(0).mean() * 100)
        drawdown = float((close / close.cummax() - 1).min() * 100)
        position = 0.0 if high == low else (latest - low) / (high - low) * 100
        accepted = (gap <= 35 and unchanged <= 35 and zero_volume <= 10 and
                    drawdown >= -70 and position >= 30)
        return QualityAssessment(accepted, gap, unchanged, zero_volume, drawdown, position)


class RisingWavePolicy:
    """Requires a multi-day advance instead of a single jump from a flat base."""

    def __init__(self, minimum_gain_pct: float = 10.0, minimum_days: int = 5,
                 maximum_days: int = 40, minimum_up_days: int = 3,
                 maximum_single_day_share: float = 0.6, lookback_days: int = 120):
        self.minimum_gain = minimum_gain_pct / 100.0
        self.minimum_days, self.maximum_days = int(minimum_days), int(maximum_days)
        self.minimum_up_days = int(minimum_up_days)
        self.maximum_single_day_share = float(maximum_single_day_share)
        self.lookback_days = int(lookback_days)

    def assess(self, frame: pd.DataFrame) -> RisingWaveAssessment:
        close = pd.to_numeric(
            frame.sort_values("trade_date").drop_duplicates("trade_date").close,
            errors="coerce",
        ).dropna().tail(self.lookback_days).to_numpy(dtype=float)
        if len(close) < self.minimum_days:
            return RisingWaveAssessment(False, 0.0, 0)
        daily = np.diff(close) / close[:-1]
        positive_counts = np.r_[0, np.cumsum(daily > 0)]
        positive_daily = pd.Series(np.maximum(daily, 0.0))
        best_gain, best_days = 0.0, 0
        for days in range(self.minimum_days, min(self.maximum_days, len(close)) + 1):
            width = days - 1
            gains = close[width:] / close[:-width] - 1.0
            up_days = positive_counts[width:] - positive_counts[:-width]
            largest_day = positive_daily.rolling(width).max().to_numpy()[width - 1:]
            accepted = ((gains >= self.minimum_gain) & (up_days >= self.minimum_up_days) &
                        (largest_day <= gains * self.maximum_single_day_share))
            if accepted.any():
                gain = float(gains[accepted].max())
                if gain > best_gain:
                    best_gain, best_days = gain, days
        return RisingWaveAssessment(best_days > 0, best_gain * 100.0, best_days)


class LongTermTrendPolicy:
    """Requires a rising 60/120-day structure without a one-candle overextension."""

    def __init__(self, maximum_ma60_extension_pct: float = 30.0):
        self.maximum_extension = float(maximum_ma60_extension_pct)

    def assess(self, frame: pd.DataFrame) -> LongTermTrendAssessment:
        close = pd.to_numeric(
            frame.sort_values("trade_date").drop_duplicates("trade_date").close,
            errors="coerce",
        ).dropna()
        if len(close) < 140:
            return LongTermTrendAssessment(False, *(float("nan"),) * 4)
        ma60, ma120 = close.rolling(60).mean(), close.rolling(120).mean()
        latest = float(close.iloc[-1])
        over60 = (latest / float(ma60.iloc[-1]) - 1.0) * 100
        over120 = (latest / float(ma120.iloc[-1]) - 1.0) * 100
        alignment = (float(ma60.iloc[-1]) / float(ma120.iloc[-1]) - 1.0) * 100
        direction = (float(ma120.iloc[-1]) / float(ma120.iloc[-21]) - 1.0) * 100
        accepted = (0 < over60 <= self.maximum_extension and over120 > 0 and
                    alignment > 0 and direction > 0)
        return LongTermTrendAssessment(accepted, over60, over120, alignment, direction)
