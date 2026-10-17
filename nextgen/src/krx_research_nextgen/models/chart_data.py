from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd

from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY


TIMEFRAME_LABELS = {"D": "일봉", "W": "주봉", "M": "월봉", "Q": "분기봉", "Y": "년봉"}
TIMEFRAME_RULES = {"W": "W-FRI", "M": "ME", "Q": "QE-DEC", "Y": "YE-DEC"}
TIMEFRAME_LOAD_FACTORS = {"D": 1, "W": 5, "M": 23, "Q": 66, "Y": 252}
STRATEGY_OPTIONS = ("전체", "엘리어트 파동", "제시 리버모어", "알렉산더 엘더")


@dataclass(frozen=True)
class StrategyAssessment:
    strategy: str
    state: str
    detail: str
    points: tuple[tuple[pd.Timestamp, float, str], ...] = ()
    levels: tuple[tuple[str, float, str], ...] = ()

    def text(self) -> str:
        return f"[{self.strategy}]\n현재 판단: {self.state}\n{self.detail}"

    def overlay_text(self) -> str:
        return f"{self.strategy}: {self.state}"


@dataclass(frozen=True)
class IndicatorConfig:
    rsi_period: float = float(DEFAULT_CHART_ANALYSIS_POLICY.rsi.periods[0])
    rsi_signal: int = DEFAULT_CHART_ANALYSIS_POLICY.rsi.periods[1]
    macd_fast: int = DEFAULT_CHART_ANALYSIS_POLICY.macd_oscillator.periods[0]
    macd_slow: int = DEFAULT_CHART_ANALYSIS_POLICY.macd_oscillator.periods[1]
    macd_signal: int = DEFAULT_CHART_ANALYSIS_POLICY.macd_oscillator.periods[2]
    bollinger_window: int = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
    bollinger_std: float = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.deviations
    stochastic_window: int = DEFAULT_CHART_ANALYSIS_POLICY.stochastic_slow.periods[0]
    stochastic_smooth: int = DEFAULT_CHART_ANALYSIS_POLICY.stochastic_slow.periods[1]
    stochastic_signal: int = DEFAULT_CHART_ANALYSIS_POLICY.stochastic_slow.periods[2]
    ema_windows: tuple[int, ...] = DEFAULT_CHART_ANALYSIS_POLICY.moving_average_periods


@dataclass(frozen=True)
class ChartBundle:
    symbol: str
    frame: pd.DataFrame
    investor_flow: pd.DataFrame = field(default_factory=pd.DataFrame)
    assessments: tuple[StrategyAssessment, ...] = ()
