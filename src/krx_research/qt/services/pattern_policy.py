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
