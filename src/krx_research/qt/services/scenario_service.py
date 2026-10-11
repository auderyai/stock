from __future__ import annotations

import numpy as np
import pandas as pd

from krx_research.analytics.indicator_scenario import (
    INDICATORS,
    evaluate,
    features_from_ohlcv,
    scenario_path,
)
from krx_research.qt.models.scenario import ScenarioAnalysis, ScenarioRequest


class ScenarioService:
    """Application service for the original workstation indicator scenario."""

    def __init__(self, market_repository):
        self._market_repository = market_repository

    @staticmethod
    def current_features(daily: pd.DataFrame) -> pd.Series:
        return features_from_ohlcv(daily).iloc[-1]

    def build_request(
        self,
        daily: pd.DataFrame,
        market: str,
        indicator: str,
        target_text: str,
        horizon_text: str,
        lookback_text: str,
    ) -> ScenarioRequest:
        if indicator not in INDICATORS:
            raise ValueError("목록에서 보조지표를 선택하세요.")
        current = self.current_features(daily)
        current_value = float(current[INDICATORS[indicator]])
        if not np.isfinite(current_value):
            raise ValueError(f"{indicator} 계산에 필요한 거래일이 부족합니다.")
        try:
            target = float(target_text.strip()) if target_text.strip() else current_value
            horizon = int(horizon_text.strip()) if horizon_text.strip() else min(20, max(1, len(daily) // 3))
            lookback = None if lookback_text.strip() in ("", "전체") else int(lookback_text.strip())
        except ValueError as exc:
            raise ValueError("목표값은 숫자, 도달 기간과 학습일수는 정수로 입력하세요.") from exc
        return ScenarioRequest(indicator, target, horizon, lookback, market)

    def calculate(self, daily: pd.DataFrame, request: ScenarioRequest) -> ScenarioAnalysis:
        market_bars = pd.DataFrame()
        try:
            market_bars = self._market_repository.load_index(request.market)
        except Exception:
            # Original workstation behavior: market context is optional and the
            # stock-only model remains available when index data cannot be read.
            market_bars = pd.DataFrame()
        market_arg = market_bars if not market_bars.empty else None
        rows = evaluate(
            daily,
            request.indicator,
            request.target,
            request.horizon,
            request.lookback,
            market_arg,
        )
        path = scenario_path(
            daily,
            request.indicator,
            request.target,
            request.horizon,
            request.lookback,
            market_arg,
        )
        history = features_from_ohlcv(daily)
        return ScenarioAnalysis(
            checkpoints=tuple(rows),
            path=path,
            current_features=history.iloc[-1],
            historical_features=history,
            market_index_name=self._market_repository.index_name(request.market),
        )
