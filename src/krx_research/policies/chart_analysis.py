from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class OscillatorPolicy:
    source: str
    periods: tuple[int, ...]
    smoothing: str = "EMA"


@dataclass(frozen=True, slots=True)
class BollingerPolicy:
    source: str = "close"
    period: int = 20
    deviations: float = 2.0
    center: str = "EMA"


@dataclass(frozen=True, slots=True)
class MarketContextPolicy:
    indices: tuple[tuple[str, str], ...] = (("KOSPI", "1001"), ("KOSDAQ", "2001"))
    volatility_days: int = 3
    source: str = "Stock PostgreSQL"


@dataclass(frozen=True, slots=True)
class ChartAnalysisPolicy:
    """User-approved, immutable settings checked before chart analysis or learning."""

    rsi: OscillatorPolicy = OscillatorPolicy("close", (14, 9))
    macd_oscillator: OscillatorPolicy = OscillatorPolicy("close", (12, 26, 9))
    stochastic_slow: OscillatorPolicy = OscillatorPolicy("close", (5, 3, 3))
    moving_average_kind: str = "EMA"
    moving_average_periods: tuple[int, ...] = (5, 10, 15, 33, 56, 112, 224, 448)
    bollinger: BollingerPolicy = BollingerPolicy()
    volume_source: str = "Stock PostgreSQL"
    market_context: MarketContextPolicy = MarketContextPolicy()
    version: int = 1

    def __post_init__(self) -> None:
        if self.moving_average_kind != "EMA" or len(self.moving_average_periods) != 8:
            raise ValueError("이동평균은 승인된 EMA 8개 설정이어야 합니다.")
        if self.volume_source != "Stock PostgreSQL" or self.market_context.source != "Stock PostgreSQL":
            raise ValueError("거래량과 시장지수는 Stock PostgreSQL 자료만 사용할 수 있습니다.")

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_CHART_ANALYSIS_POLICY = ChartAnalysisPolicy()
