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
