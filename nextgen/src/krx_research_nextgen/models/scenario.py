from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    indicator: str
    target: float
    horizon: int
    lookback: int | None = None


@dataclass(frozen=True, slots=True)
class ScenarioCheckpoint:
    days: int
    baseline_price: float
    scenario_price: float
    lower_price: float
    upper_price: float
    mae: float
    naive_mae: float
    direction: float
    signal: str
    train_period: str
    test_period: str


@dataclass(frozen=True, slots=True)
class ScenarioAnalysis:
    current_price: float
    current_value: float
    achieved_value: float
    requested_value: float
    path: pd.DataFrame
    checkpoints: tuple[ScenarioCheckpoint, ...]
    feasible: bool
    return_limits: tuple[float, float]
