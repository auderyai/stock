from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


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
    rsi_period: float = 14.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_window: int = 20
    bollinger_std: float = 2.0
    stochastic_window: int = 5
    stochastic_smooth: int = 3
    ema_windows: tuple[int, ...] = (5, 10, 15, 33, 56, 112, 224, 448)


@dataclass(frozen=True)
class ChartBundle:
    symbol: str
    frame: pd.DataFrame
    investor_flow: pd.DataFrame = field(default_factory=pd.DataFrame)
    assessments: tuple[StrategyAssessment, ...] = ()
