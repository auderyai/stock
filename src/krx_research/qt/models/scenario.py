from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from krx_research.analytics.indicator_scenario import Checkpoint, PathResult


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    indicator: str
    target: float
    horizon: int
    lookback: int | None
    market: str


@dataclass(frozen=True, slots=True)
class ScenarioAnalysis:
    checkpoints: tuple[Checkpoint, ...]
    path: PathResult
    current_features: pd.Series
    historical_features: pd.DataFrame
    market_index_name: str
