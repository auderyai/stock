from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY


EMA_SPANS = DEFAULT_CHART_ANALYSIS_POLICY.moving_average_periods
INDICATORS = {
    "RSI(14)": "rsi", "Slow %K(5,3,3)": "stoch_slow_k",
    "MACD oscillator (% price)": "macd_pct", "Bollinger position (sigma)": "bb_z",
    "EMA 5 gap (%)": "ema5_gap", "EMA 15 gap (%)": "ema15_gap",
    **{f"EMA {n} 일별 변화율 (%)": f"ema{n}_change_pct" for n in EMA_SPANS},
}


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
