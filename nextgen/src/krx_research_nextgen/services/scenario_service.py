from __future__ import annotations

import numpy as np
import pandas as pd

from krx_research_nextgen.models.scenario import (
    EMA_SPANS, INDICATORS, ScenarioAnalysis, ScenarioCheckpoint, ScenarioRequest,
)
from krx_research_nextgen.services.technical_analysis_service import TechnicalAnalysisService
from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY


class ScenarioService:
    """Qt/DB-free chronological indicator-scenario engine."""

    def __init__(self, technical: TechnicalAnalysisService | None = None) -> None:
        self._technical = technical or TechnicalAnalysisService()

    def current_value(self, frame: pd.DataFrame, indicator: str) -> float:
        value = self._features(frame)[INDICATORS[indicator]].dropna()
        if value.empty: raise ValueError(f"{indicator} 계산에 필요한 거래일이 부족합니다.")
        return float(value.iloc[-1])

    def request(self, frame: pd.DataFrame, indicator: str, target: str, horizon: str, lookback: str) -> ScenarioRequest:
        if indicator not in INDICATORS: raise ValueError("목록에서 보조지표를 선택하세요.")
        current = self.current_value(frame, indicator)
        try:
            days = int(horizon.strip() or 20); period = None if lookback.strip() in ("", "전체") else int(lookback)
            goal = float(target.strip()) if target.strip() else current
        except ValueError as exc:
            raise ValueError("목표값은 숫자, 도달 기간과 학습 기간은 정수로 입력하세요.") from exc
        if not np.isfinite(goal) or not 1 <= days <= 60: raise ValueError("목표값과 1~60 거래일의 도달 기간을 확인하세요.")
        if period is not None and not 80 <= period <= 20_000: raise ValueError("학습 기간은 80~20000 거래일 또는 빈칸이어야 합니다.")
        if indicator.startswith(("RSI", "Slow")) and not 0 <= goal <= 100: raise ValueError("RSI와 스토캐스틱 목표값은 0~100입니다.")
        return ScenarioRequest(indicator, goal, days, period)

    def analyze(self, frame: pd.DataFrame, request: ScenarioRequest) -> ScenarioAnalysis:
        base = frame.loc[:, ["open", "high", "low", "close", "volume"]].dropna().copy()
        if request.lookback: base = base.tail(request.lookback)
        if len(base) < 80: raise ValueError("시간순 학습·검증에는 최소 80거래일이 필요합니다.")
        features, column = self._features(base), INDICATORS[request.indicator]
        current = float(features[column].dropna().iloc[-1]); price = float(base.close.iloc[-1])
        path, achieved, feasible, limits = self._scenario_path(base, column, request.target, request.horizon)
        checkpoints = tuple(self._forecast(features, column, current, request.target, request.horizon, days) for days in sorted({1, max(1, request.horizon // 2), request.horizon}))
        return ScenarioAnalysis(price, current, achieved, request.target, path, checkpoints, feasible, limits)

    def _features(self, frame: pd.DataFrame) -> pd.DataFrame:
        df = self._technical.enrich(frame.loc[:, ["open", "high", "low", "close", "volume"]])
        close = df.close.astype(float); out = df.copy()
        out["ret1"] = close.pct_change(fill_method=None) * 100
        out["ret5"] = close.pct_change(5, fill_method=None) * 100
        out["volatility20"] = out.ret1.rolling(20).std()
        out["volume_ratio"] = df.volume / df.volume.rolling(20).mean().replace(0, np.nan)
        out["macd_pct"] = out.macd_hist / close * 100
        bollinger_period = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
        out["bb_z"] = (
            (close - out.bb_mid)
            / close.rolling(bollinger_period).std(ddof=0).replace(0, np.nan)
        )
        for n in EMA_SPANS:
            out[f"ema{n}_change_pct"] = out[f"ema_{n}"].pct_change(fill_method=None) * 100
        out["ema5_gap"] = (close / out.ema_5 - 1) * 100; out["ema15_gap"] = (close / out.ema_15 - 1) * 100
        return out.replace([np.inf, -np.inf], np.nan)

    def _forecast(self, frame: pd.DataFrame, column: str, current: float, target: float, horizon: int, days: int) -> ScenarioCheckpoint:
        columns = list(dict.fromkeys(["ret1", "ret5", "volatility20", "volume_ratio", "rsi", "stoch_slow_k", "macd_pct", "bb_z", "ema5_gap", "ema15_gap", column]))
        data = frame.assign(label=(frame.close.shift(-days) / frame.close - 1) * 100).dropna(subset=[*columns, "label"])
        if len(data) < 25: raise ValueError(f"{days}일 예측에 필요한 학습 자료가 부족합니다.")
        cut = max(15, int(len(data) * .8) - days); train, test = data.iloc[:cut], data.iloc[cut + days:]
        if test.empty: test = data.tail(max(3, len(data) // 5))
        mean, std = train[columns].mean(), train[columns].std().replace(0, 1)
        x = (train[columns] - mean) / std; design = np.c_[np.ones(len(x)), x]
        beta = np.linalg.solve(design.T @ design + np.eye(design.shape[1]) * .5, design.T @ train.label)
        predict = lambda rows: np.c_[np.ones(len(rows)), (rows[columns] - mean) / std] @ beta
        errors = test.label.to_numpy() - predict(test); mae = float(np.mean(np.abs(errors))); naive = float(np.mean(np.abs(test.label)))
        now = frame.iloc[[-1]].copy(); altered = now.copy(); altered[column] = current + (target - current) * days / horizon
        baseline, scenario = float(predict(now)[0]), float(predict(altered)[0]); low, high = np.quantile(errors, [.1, .9])
        threshold = max(1.0, float(np.quantile(np.abs(errors), .75)))
        signal = "신호 보류 (검증 기준 미달)" if mae >= naive else "매수 검토" if scenario > threshold and scenario + low > 0 else "매도 검토" if scenario < -threshold and scenario + high < 0 else "관망"
        direction = float((np.sign(predict(test)) == np.sign(test.label)).mean() * 100)
        period = lambda rows: f"{rows.index[0].date()}~{rows.index[-1].date()} ({len(rows)}건)"
        return ScenarioCheckpoint(days, *(float(frame.close.iloc[-1] * (1 + value / 100)) for value in (baseline, scenario, scenario + low, scenario + high)), mae, naive, direction, signal, period(train), period(test))

    def _scenario_path(self, base: pd.DataFrame, column: str, target: float, horizon: int) -> tuple[pd.DataFrame, float, bool, tuple[float, float]]:
        returns = base.close.shift(-horizon).div(base.close).sub(1).dropna(); limits = tuple(float(x) for x in returns.quantile([.01, .99]))
        last = float(base.close.iloc[-1]); recent = base.tail(20); volume = float(recent.volume.median())
        hi = float((recent.high / recent[["open", "close"]].max(axis=1) - 1).clip(lower=0).median())
        lo = float((1 - recent.low / recent[["open", "close"]].min(axis=1)).clip(lower=0).median())
        dates = pd.bdate_range(base.index[-1] + pd.offsets.BDay(1), periods=horizon)
        def candidate(ret: float) -> tuple[float, pd.DataFrame]:
            close = last * np.exp(np.log1p(ret) * np.arange(1, horizon + 1) / horizon); open_ = np.r_[last, close[:-1]]
            future = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * (1 + hi), "low": np.minimum(open_, close) * (1 - lo), "close": close, "volume": volume}, index=dates)
            enriched = self._features(pd.concat([base, future])).tail(horizon)
            return float(enriched[column].iloc[-1]), enriched
        bounds = (min(limits[0], -.5), max(limits[1], 1.5)); choices = [(abs(value - target), value, path) for ret in np.linspace(*bounds, 121) for value, path in [candidate(float(ret))] if np.isfinite(value)]
        error, achieved, path = min(choices, key=lambda item: item[0]); return path, achieved, error <= max(.05, abs(target) * .005), limits
