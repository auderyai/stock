"""Deterministic, read-only classic-strategy summaries for the chart window."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pandas import DataFrame, Series

ALL_STRATEGIES = "전체"
ELLIOTT_WAVE = "엘리어트 파동"
JESSE_LIVERMORE = "제시 리버모어"
ALEXANDER_ELDER = "알렉산더 엘더"
STRATEGY_OPTIONS = (
    ALL_STRATEGIES,
    ELLIOTT_WAVE,
    JESSE_LIVERMORE,
    ALEXANDER_ELDER,
)


@dataclass(frozen=True)
class ClassicStrategyAssessment:
    """One transparent rule-based strategy assessment."""

    strategy: str
    state: str
    detail: str

    def display_text(self) -> str:
        return f"{self.strategy}: {self.state} — {self.detail}"


def _percentage_change(series: Series, periods: int) -> float:
    if len(series) <= periods:
        return float("nan")
    previous = float(series.iloc[-periods - 1])
    if previous == 0:
        return float("nan")
    return (float(series.iloc[-1]) / previous - 1.0) * 100.0


def _format_percentage(value: float) -> str:
    return "자료부족" if not np.isfinite(value) else f"{value:+.1f}%"


def _elliott_wave(daily: DataFrame) -> ClassicStrategyAssessment:
    required = {"close", "high", "ema_33", "ema_56"}
    if len(daily) < 60 or not required.issubset(daily.columns):
        return ClassicStrategyAssessment(
            ELLIOTT_WAVE,
            "자료부족",
            "최소 60거래일과 EMA 33·56이 필요합니다.",
        )

    last = daily.iloc[-1]
    close = float(last["close"])
    ema33 = float(last["ema_33"])
    ema56 = float(last["ema_56"])
    if not all(np.isfinite(value) for value in (close, ema33, ema56)):
        return ClassicStrategyAssessment(
            ELLIOTT_WAVE,
            "자료부족",
            "현재 EMA 33·56 계산값이 없습니다.",
        )

    return20 = _percentage_change(daily["close"], 20)
    return60 = _percentage_change(daily["close"], 60)
    high60 = float(daily["high"].tail(60).max())
    drawdown = (close / high60 - 1.0) * 100.0 if high60 > 0 else float("nan")
    if close > ema33 > ema56 and return20 > 0:
        state = "상승파동 후보"
    elif close > ema56 and return60 > 0 and return20 <= 0:
        state = "상승추세 내 조정 후보"
    elif close < ema33 < ema56:
        state = "하락파동 후보"
    else:
        state = "파동 전환 확인"
    detail = (
        f"계산 기준일 {daily.index[-1]:%Y-%m-%d}; 현재 종가를 기준으로 "
        f"20일 {_format_percentage(return20)}, 60일 {_format_percentage(return60)}, "
        f"60일 고점 대비 {_format_percentage(drawdown)}; 파동 번호는 확정하지 않습니다."
    )
    return ClassicStrategyAssessment(ELLIOTT_WAVE, state, detail)


def _jesse_livermore(daily: DataFrame) -> ClassicStrategyAssessment:
    required = {"close", "high", "volume", "ema_33", "ema_56", "prior_high_52w"}
    if len(daily) < 56 or not required.issubset(daily.columns):
        return ClassicStrategyAssessment(
            JESSE_LIVERMORE,
            "자료부족",
            "최소 56거래일과 추세·신고가 자료가 필요합니다.",
        )

    last = daily.iloc[-1]
    close = float(last["close"])
    high = float(last["high"])
    ema33 = float(last["ema_33"])
    ema56 = float(last["ema_56"])
    prior_high = float(last["prior_high_52w"])
    average_volume = float(daily["volume"].tail(20).mean())
    volume_ratio = (
        float(last["volume"]) / average_volume
        if average_volume > 0
        else float("nan")
    )
    trend_up = close > ema33 > ema56
    breakout = np.isfinite(prior_high) and high > prior_high
    if trend_up and breakout and volume_ratio >= 1.2:
        state = "신고가·거래량 돌파"
    elif trend_up and breakout:
        state = "신고가 돌파"
    elif trend_up:
        state = "상승추세 관찰"
    elif close < ema56:
        state = "추세 이탈 주의"
    else:
        state = "중립"
    breakout_text = "돌파" if breakout else "미돌파"
    detail = (
        f"계산 기준일 {daily.index[-1]:%Y-%m-%d}; 52주 이전 고점 {breakout_text}, 거래량은 20일 평균의 "
        f"{volume_ratio:.2f}배, 종가/EMA33/EMA56 추세를 함께 판정했습니다."
    )
    return ClassicStrategyAssessment(JESSE_LIVERMORE, state, detail)


def _alexander_elder(daily: DataFrame, weekly: DataFrame) -> ClassicStrategyAssessment:
    required_daily = {"stoch_slow_k", "stoch_slow_d"}
    if (
        len(daily) < 2
        or len(weekly) < 35
        or not required_daily.issubset(daily.columns)
        or "close" not in weekly
    ):
        return ClassicStrategyAssessment(
            ALEXANDER_ELDER,
            "자료부족",
            "주봉 MACD와 일봉 Slow Stochastic 판정 자료가 부족합니다.",
        )

    weekly_close = weekly["close"].astype("float64")
    weekly_ema13 = weekly_close.ewm(span=13, adjust=False, min_periods=13).mean()
    weekly_macd = weekly_close.ewm(span=12, adjust=False, min_periods=12).mean() - (
        weekly_close.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    weekly_signal = weekly_macd.ewm(span=9, adjust=False, min_periods=9).mean()
    weekly_oscillator = weekly_macd - weekly_signal
    oscillator = weekly_oscillator.dropna()
    stochastic = daily[["stoch_slow_k", "stoch_slow_d"]].dropna()
    if len(oscillator) < 2 or len(stochastic) < 2:
        return ClassicStrategyAssessment(
            ALEXANDER_ELDER,
            "자료부족",
            "완성된 주봉 MACD 또는 일봉 Slow Stochastic 값이 부족합니다.",
        )

    current_k = float(stochastic.iloc[-1]["stoch_slow_k"])
    current_d = float(stochastic.iloc[-1]["stoch_slow_d"])
    previous_k = float(stochastic.iloc[-2]["stoch_slow_k"])
    previous_d = float(stochastic.iloc[-2]["stoch_slow_d"])
    weekly_rising = float(oscillator.iloc[-1]) > float(oscillator.iloc[-2])
    weekly_up = weekly_rising and float(weekly_close.iloc[-1]) > float(weekly_ema13.iloc[-1])
    cross_up = previous_k <= previous_d and current_k > current_d
    cross_down = previous_k >= previous_d and current_k < current_d

    if weekly_up and cross_up and current_k <= 50:
        state = "삼중창 매수 후보"
    elif weekly_up and current_k >= 80:
        state = "주봉 상승·단기 과열"
    elif weekly_up:
        state = "주봉 상승·일봉 대기"
    elif not weekly_rising and cross_down:
        state = "하락 위험"
    else:
        state = "중립"
    direction = "상승" if weekly_rising else "하락"
    detail = (
        f"계산 기준일 {daily.index[-1]:%Y-%m-%d}; 주봉 MACD 오실레이터 {direction}, 일봉 Slow %K {current_k:.1f}, "
        f"%D {current_d:.1f}입니다."
    )
    return ClassicStrategyAssessment(ALEXANDER_ELDER, state, detail)


def assess_classic_strategies(
    daily: DataFrame,
    weekly: DataFrame,
) -> tuple[ClassicStrategyAssessment, ...]:
    """Assess all supported strategies without network or database writes."""

    if daily.empty:
        raise ValueError("고전전략을 판정할 일봉 자료가 없습니다.")
    return (
        _elliott_wave(daily),
        _jesse_livermore(daily),
        _alexander_elder(daily, weekly),
    )


def format_strategy_assessments(
    assessments: tuple[ClassicStrategyAssessment, ...],
    selected: str = ALL_STRATEGIES,
) -> str:
    """Format one or all assessments for the compact legacy GUI result panel."""

    if selected not in STRATEGY_OPTIONS:
        raise ValueError(f"지원하지 않는 고전전략입니다: {selected}")
    rows = (
        assessments
        if selected == ALL_STRATEGIES
        else tuple(item for item in assessments if item.strategy == selected)
    )
    return "\n".join(item.display_text() for item in rows)
