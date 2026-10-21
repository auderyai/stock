from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

import numpy as np
import pandas as pd

from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY
from krx_research.qt.models.pattern import PatternRepository
from krx_research.qt.models.pattern_queries import CurrentPatternKind, CurrentPatternQuery

from .pattern_policy import PatternQualityPolicy


class PatternStage(str, Enum):
    FORMING = "형성 중"
    READY = "돌파 대기"
    CONFIRMED = "최근 돌파·구조 유지"


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    kind: CurrentPatternKind
    stage: PatternStage
    start: date
    pivot: date
    end: date
    score: float
    resistance: float
    invalidation: float
    breakout: date | None
    evidence: str


class SwingPoints:
    """Extracts volatility-adaptive extrema without fixing one pattern duration."""

    @staticmethod
    def extrema(values: np.ndarray, low: bool) -> list[int]:
        count = len(values)
        radius = max(2, min(8, count // 35))
        points = []
        for index in range(radius, count - radius):
            window = values[index - radius:index + radius + 1]
            target = np.nanmin(window) if low else np.nanmax(window)
            if np.isfinite(values[index]) and values[index] == target:
                if not points or index - points[-1] > radius:
                    points.append(index)
                elif ((low and values[index] < values[points[-1]]) or
                      (not low and values[index] > values[points[-1]])):
                    points[-1] = index
        return points


class DoubleBottomDetector:
    kind = CurrentPatternKind.DOUBLE_BOTTOM

    def detect(self, frame: pd.DataFrame) -> PatternCandidate | None:
        data = _prepared(frame, 260)
        if len(data) < 45:
            return None
        close = data.close.to_numpy(float)
        smooth = pd.Series(close).ewm(
            span=DEFAULT_CHART_ANALYSIS_POLICY.moving_average_periods[0],
            adjust=False,
        ).mean().to_numpy()
        lows = SwingPoints.extrema(smooth, True)
        best = None
        for first, second in ((a, b) for a in lows for b in lows if 8 <= b - a <= 110):
            if len(close) - second > 65:
                continue
            neckline_index = first + int(np.argmax(smooth[first:second + 1]))
            neckline = float(smooth[neckline_index])
            bottom = (smooth[first] + smooth[second]) / 2
            similarity = abs(smooth[first] / smooth[second] - 1)
            depth = neckline / bottom - 1
            if similarity > 0.10 or not 0.08 <= depth <= 0.65:
                continue
            candidate = self._candidate(data, close, first, second, neckline_index,
                                        neckline, similarity, depth)
            if candidate and (best is None or candidate.score > best.score):
                best = candidate
        return best

    def _candidate(self, data, close, first, second, neckline_index, neckline,
                   similarity, depth) -> PatternCandidate | None:
        latest = close[-1]
        breakout_positions = np.flatnonzero(close[second + 1:] > neckline * 1.005)
        breakout_index = second + 1 + int(breakout_positions[0]) if breakout_positions.size else None
        recovery = latest / close[second] - 1
        rising = len(close) >= 4 and close[-1] > close[-4]
        if breakout_index is not None:
            age, extension = len(close) - 1 - breakout_index, latest / neckline - 1
            if age > 20 or latest < neckline * 0.97 or not -0.03 <= extension <= 0.30:
                return None
            stage = PatternStage.CONFIRMED
        elif recovery >= 0.04 and rising and latest < neckline * 1.02:
            stage = PatternStage.READY
        elif len(close) - second <= 12 and recovery >= -0.02 and latest < neckline:
            stage = PatternStage.FORMING
        else:
            return None
        score = 62 + (1 - similarity / 0.10) * 14 + (1 - abs(depth - 0.25) / 0.40) * 9
        score += {PatternStage.FORMING: 0, PatternStage.READY: 5, PatternStage.CONFIRMED: 9}[stage]
        dates = data.trade_date.dt.date
        evidence = (f"두 저점 차이 {similarity * 100:.1f}%, 넥라인 대비 "
                    f"{(latest / neckline - 1) * 100:+.1f}%, 저점 간 {second - first}거래일")
        return PatternCandidate(
            self.kind, stage, dates.iloc[first], dates.iloc[second], dates.iloc[-1],
            round(max(0.0, min(100.0, score)), 2), neckline,
            float(min(close[first], close[second]) * 0.97),
            None if breakout_index is None else dates.iloc[breakout_index], evidence,
        )


class CupWithHandleDetector:
    kind = CurrentPatternKind.CUP_WITH_HANDLE
    WINDOWS = (60, 90, 120, 160, 220)

    def detect(self, frame: pd.DataFrame) -> PatternCandidate | None:
        data = _prepared(frame, max(self.WINDOWS))
        candidates = [self._window(data.tail(days)) for days in self.WINDOWS]
        return max((item for item in candidates if item), key=lambda item: item.score, default=None)

    def _window(self, data: pd.DataFrame) -> PatternCandidate | None:
        if len(data) < 45:
            return None
        close = data.close.to_numpy(float)
        smooth = pd.Series(close).ewm(
            span=DEFAULT_CHART_ANALYSIS_POLICY.moving_average_periods[0],
            adjust=False,
        ).mean().to_numpy()
        count = len(close)
        left = int(np.argmax(smooth[:max(12, count // 3)]))
        low_limit = max(left + 6, count // 5)
        if low_limit >= count - 12:
            return None
        bottom = low_limit + int(np.argmin(smooth[low_limit:int(count * 0.78)]))
        if bottom >= count - 10:
            return None
        right = bottom + 5 + int(np.argmax(smooth[bottom + 5:count - 4]))
        handle = close[right + 1:]
        if len(handle) < 4:
            return None
        rim = (smooth[left] + smooth[right]) / 2
        rim_difference = abs(smooth[left] / smooth[right] - 1)
        depth = 1 - smooth[bottom] / rim
        handle_low_index = right + 1 + int(np.argmin(handle))
        handle_depth = 1 - close[handle_low_index] / smooth[right]
        bottom_width = int(np.sum(smooth[left:right + 1] <= smooth[bottom] * 1.10))
        if (rim_difference > 0.15 or not 0.10 <= depth <= 0.55 or
                not 0.015 <= handle_depth <= min(0.20, depth * 0.55) or bottom_width < 3):
            return None
        return self._candidate(data, close, left, bottom, right, handle_low_index,
                               rim, rim_difference, depth, handle_depth)

    def _candidate(self, data, close, left, bottom, right, handle_low, rim,
                   rim_difference, depth, handle_depth) -> PatternCandidate | None:
        latest = close[-1]
        breakout_positions = np.flatnonzero(close[right + 1:] > rim * 1.005)
        breakout_index = right + 1 + int(breakout_positions[0]) if breakout_positions.size else None
        rising = len(close) >= 4 and close[-1] > close[-4]
        if breakout_index is not None:
            age, extension = len(close) - 1 - breakout_index, latest / rim - 1
            if age > 20 or latest < rim * 0.97 or not -0.03 <= extension <= 0.30:
                return None
            stage = PatternStage.CONFIRMED
        elif rising and latest >= close[handle_low] * 1.03 and latest < rim * 1.02:
            stage = PatternStage.READY
        elif len(close) - handle_low <= 15 and latest < rim:
            stage = PatternStage.FORMING
        else:
            return None
        score = (60 + (1 - rim_difference / 0.15) * 12 +
                 (1 - abs(depth - 0.28) / 0.27) * 9 +
                 (1 - handle_depth / 0.20) * 8)
        score += {PatternStage.FORMING: 0, PatternStage.READY: 4, PatternStage.CONFIRMED: 8}[stage]
        dates = data.trade_date.dt.date
        evidence = (f"컵 깊이 {depth * 100:.1f}%, 양쪽 림 차이 {rim_difference * 100:.1f}%, "
                    f"손잡이 조정 {handle_depth * 100:.1f}%")
        return PatternCandidate(
            self.kind, stage, dates.iloc[left], dates.iloc[bottom], dates.iloc[-1],
            round(max(0.0, min(100.0, score)), 2), rim,
            float(close[handle_low] * 0.97),
            None if breakout_index is None else dates.iloc[breakout_index], evidence,
        )


class CurrentPatternSearchService:
    """Finds active structures only; it never emits a trading recommendation."""

    def __init__(self, repository: PatternRepository):
        self.repository = repository
        self.quality = PatternQualityPolicy()
        self.detectors = {
            CurrentPatternKind.DOUBLE_BOTTOM: DoubleBottomDetector(),
            CurrentPatternKind.CUP_WITH_HANDLE: CupWithHandleDetector(),
        }

    def search(self, query: CurrentPatternQuery) -> list[dict]:
        latest = self.repository.latest_date()
        history = self.repository.history(latest - timedelta(days=760), latest)
        if "market" in history:
            history = history.loc[history.market.isin(("KOSPI", "KOSDAQ"))]
        detector = self.detectors[query.kind]
        found = []
        for code, frame in history.groupby("stock_code", sort=False):
            if not self.quality.assess(frame).accepted:
                continue
            candidate = detector.detect(frame)
            if candidate is not None:
                found.append((candidate.score, str(code), candidate, frame))
        found.sort(key=lambda item: (-item[0], item[1]))
        selected = found[:query.top_n]
        if not selected:
            raise ValueError("현재 조건을 충족하는 종목이 없습니다. 0건을 성공으로 처리하지 않습니다.")
        snapshots = self.repository.latest([item[1] for item in selected])
        market = MarketContextAnalyzer(self.repository.market_context(latest))
        return [self._row(code, candidate, frame, snapshots.get(code, {}), market)
                for _, code, candidate, frame in selected]

    @staticmethod
    def _row(code: str, candidate: PatternCandidate, frame: pd.DataFrame,
             snapshot: dict, market: "MarketContextAnalyzer") -> dict:
        value = lambda key: snapshot.get(key)
        eok = lambda key: None if value(key) is None else round(float(value(key)) / 100_000_000, 2)
        latest = float(frame.sort_values("trade_date").close.iloc[-1])
        context = market.assess(frame, str(value("market") or ""))
        return {
            "stock_code": code, "stock_name": value("stock_name") or str(frame.stock_name.iloc[-1]),
            "pattern_kind": candidate.kind.value, "pattern_stage": candidate.stage.value,
            "pattern_score": candidate.score, "pattern_start": candidate.start,
            "pattern_pivot": candidate.pivot, "pattern_end": candidate.end,
            "breakout_date": candidate.breakout, "resistance": round(candidate.resistance, 2),
            "invalidation": round(candidate.invalidation, 2),
            "distance_to_resistance_pct": round((latest / candidate.resistance - 1) * 100, 2),
            "risk_to_invalidation_pct": round((latest / candidate.invalidation - 1) * 100, 2),
            "pattern_evidence": candidate.evidence, "db_recent_date": value("trade_date"),
            **context,
            "rise_pct": value("rise_pct"), "close": value("close"),
            "market_cap_eok": eok("market_cap"), "trading_value_eok": eok("trading_value"),
        }


class MarketContextAnalyzer:
    """Reports market regime and relative strength as evidence, not a buy/sell rule."""

    INDEX = {"KOSPI": "1001", "KOSDAQ": "2001"}

    def __init__(self, frame: pd.DataFrame):
        self.indices = {
            str(code): group.sort_values("trade_date").set_index("trade_date")["close"].astype(float)
            for code, group in frame.groupby("index_code")
        }

    def assess(self, stock: pd.DataFrame, market: str) -> dict:
        code = self.INDEX.get(market.upper())
        if code not in self.indices:
            raise ValueError(f"{market or '종목'}의 시장 종합지수 자료를 연결할 수 없습니다.")
        index = self.indices[code]
        stock_close = stock.sort_values("trade_date").set_index("trade_date")["close"].astype(float)
        aligned = pd.concat([stock_close.rename("stock"), index.rename("market")], axis=1).dropna()
        returns = aligned.pct_change(fill_method=None).dropna().tail(60)
        if len(returns) < 20:
            raise ValueError(f"{market} 시장 조정 통계를 계산할 공통 거래일이 부족합니다.")
        horizon = min(20, len(aligned) - 1)
        stock_return = (aligned.stock.iloc[-1] / aligned.stock.iloc[-horizon - 1] - 1) * 100
        market_return = (aligned.market.iloc[-1] / aligned.market.iloc[-horizon - 1] - 1) * 100
        variance = returns.market.var(ddof=0)
        beta = 0.0 if variance == 0 else returns.cov(ddof=0).loc["stock", "market"] / variance
        return {
            "market_context": market, "market_return_20d_pct": round(float(market_return), 2),
            "relative_return_20d_pct": round(float(stock_return - market_return), 2),
            "market_correlation_60d": round(float(returns.corr().loc["stock", "market"]), 3),
            "market_beta_60d": round(float(beta), 3),
        }


def _prepared(frame: pd.DataFrame, length: int) -> pd.DataFrame:
    data = frame.sort_values("trade_date").drop_duplicates("trade_date").tail(length).copy()
    for column in ("close", "high", "low", "volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=["close", "high", "low", "volume"]).reset_index(drop=True)
