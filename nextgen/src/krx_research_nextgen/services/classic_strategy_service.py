from __future__ import annotations

import numpy as np
import pandas as pd

from krx_research_nextgen.models.chart_data import StrategyAssessment


class ClassicStrategyService:
    """원전의 객관화 가능한 조건만 DB 일봉으로 판정한다."""

    @staticmethod
    def _item(name, state, detail, points=(), levels=()) -> StrategyAssessment:
        return StrategyAssessment(name, state, detail, tuple(points), tuple(levels))

    def assess(self, frame: pd.DataFrame) -> tuple[StrategyAssessment, ...]:
        daily = self._prepare(frame)
        return self._elliott(daily), self._livermore(daily), self._elder(daily)

    @staticmethod
    def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
        columns = ["open", "high", "low", "close", "volume"]
        if frame.empty or any(column not in frame for column in columns): return pd.DataFrame(columns=columns)
        daily = frame.loc[:, columns].copy().sort_index()
        daily = daily.loc[~daily.index.duplicated(keep="last")].apply(pd.to_numeric, errors="coerce").dropna()
        valid = ((daily[columns[:4]] > 0).all(axis=1) & daily.volume.ge(0) &
                 daily.high.ge(daily[["open", "low", "close"]].max(axis=1)) &
                 daily.low.le(daily[["open", "high", "close"]].min(axis=1)))
        daily = daily.loc[valid]; close = daily.close.astype(float)
        low5, high5 = daily.low.rolling(5).min(), daily.high.rolling(5).max()
        fast = (close - low5) / (high5 - low5).replace(0, np.nan) * 100
        daily["slow_k"], daily["slow_d"] = fast.rolling(3).mean(), fast.rolling(3).mean().rolling(3).mean()
        return daily

    @staticmethod
    def _swings(daily: pd.DataFrame, order: int = 5) -> list[tuple[pd.Timestamp, float, str]]:
        if len(daily) < order * 2 + 1: return []
        high, low = daily.high, daily.low
        peaks = high.eq(high.rolling(order * 2 + 1, center=True).max())
        troughs = low.eq(low.rolling(order * 2 + 1, center=True).min())
        raw = sorted([(daily.index[i], float(high.iloc[i]), "H") for i in np.flatnonzero(peaks)] +
                     [(daily.index[i], float(low.iloc[i]), "L") for i in np.flatnonzero(troughs)])
        swings = []
        for point in raw:
            if swings and swings[-1][2] == point[2]:
                if (point[2] == "H" and point[1] > swings[-1][1]) or (point[2] == "L" and point[1] < swings[-1][1]): swings[-1] = point
            else: swings.append(point)
        return swings

    @staticmethod
    def _impulse(points) -> str | None:
        prices, kinds = [point[1] for point in points], "".join(point[2] for point in points)
        if kinds == "LHLHLH":
            p0, p1, p2, p3, p4, p5 = prices
            return "상승" if p1 > p0 and p3 > p2 and p5 > p4 and p2 > p0 and p4 > p1 and p3 - p2 >= min(p1 - p0, p5 - p4) else None
        if kinds == "HLHLHL":
            p0, p1, p2, p3, p4, p5 = prices
            return "하락" if p0 > p1 and p2 > p3 and p4 > p5 and p2 < p0 and p4 < p1 and p2 - p3 >= min(p0 - p1, p4 - p5) else None
        return None

    def _elliott(self, daily: pd.DataFrame) -> StrategyAssessment:
        name = "엘리어트 파동"; swings = self._swings(daily)
        for end in range(len(swings), 5, -1):
            points, direction = swings[end - 6:end], self._impulse(swings[end - 6:end])
            if direction:
                labels = tuple((date, price, str(index)) for index, (date, price, _) in enumerate(points))
                detail = (f"최근 고점과 저점의 움직임이 {direction} 방향의 5단계 파동 모양과 비슷합니다. "
                          "다만 조건에 맞는 모양을 찾았다는 뜻일 뿐, 다음 가격 방향을 예측하거나 확정한 것은 아닙니다.")
                return self._item(name, f"{direction} 5단계 파동 모양 발견", detail, labels)
        return self._item(name, "5단계 파동 모양 없음", "최근 가격 흐름에서는 5단계 파동의 필수 조건이 모두 맞는 구간을 찾지 못했습니다.")

    def _livermore(self, daily: pd.DataFrame) -> StrategyAssessment:
        name = "제시 리버모어"
        if len(daily) < 253: return self._item(name, "자료부족", "당일을 제외한 252거래일 피벗과 직전 20일 거래량 판정에는 최소 253거래일이 필요합니다.")
        last, prior = daily.iloc[-1], daily.iloc[-253:-1]
        pivot, average = float(prior.high.max()), float(prior.volume.tail(20).mean())
        ratio = float(last.volume) / average if average > 0 else np.nan
        breakout, heavy = float(last.close) > pivot, np.isfinite(ratio) and ratio >= 1.5
        state = ("최고가 돌파·거래량 증가" if breakout and heavy else "최고가 돌파·거래량 부족" if breakout else
                 "최고가에 가까움·돌파 대기" if float(last.close) >= pivot * .97 else "최고가 돌파 전")
        price = ("최근 1년 최고가를 넘어섰습니다" if breakout else
                 f"최근 1년 최고가 {pivot:,.0f}원보다 {(pivot - float(last.close)) / pivot * 100:.1f}% 낮습니다")
        volume = "넘었습니다" if heavy else "넘지 못했습니다"
        detail = (f"현재 종가는 {last.close:,.0f}원으로 {price}. 오늘 거래량은 최근 20일 평균의 "
                  f"{ratio:.2f}배로 증가 기준 1.50배를 {volume}. 가격과 거래량이 모두 기준을 만족해야 돌파 신호로 봅니다.")
        return self._item(name, state, detail, levels=(("price", pivot, "최근 1년 최고가"), ("volume", average, "직전 20일 평균 거래량")))

    def _elder(self, daily: pd.DataFrame) -> StrategyAssessment:
        name = "알렉산더 엘더"
        if len(daily) < 2: return self._item(name, "자료부족", "일봉 자료가 부족합니다.")
        weekly = daily.assign(actual_date=daily.index).groupby(daily.index.to_period("W-FRI"), sort=True).agg(close=("close", "last"), actual_date=("actual_date", "last"))
        weekly.index = pd.DatetimeIndex(weekly.actual_date); close = weekly.close.astype(float)
        macd = close.ewm(span=12, adjust=False, min_periods=12).mean() - close.ewm(span=26, adjust=False, min_periods=26).mean()
        histogram = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()).dropna()
        stochastic = daily[["slow_k", "slow_d"]].dropna()
        if len(histogram) < 2 or len(stochastic) < 1: return self._item(name, "자료부족", "완성된 주봉 MACD-Histogram과 일봉 Slow Stochastic 자료가 부족합니다.")
        rising, k = float(histogram.iloc[-1]) > float(histogram.iloc[-2]), float(stochastic.iloc[-1].slow_k)
        last, previous = daily.iloc[-1], daily.iloc[-2]
        long_setup, short_setup = rising and k < 30, not rising and k > 70
        long_entry, short_entry = long_setup and last.high > previous.high, short_setup and last.low < previous.low
        state = ("매수 조건 충족" if long_entry else "매수 관심·가격 돌파 대기" if long_setup else "매도 조건 충족" if short_entry else
                 "매도 관심·가격 하락 대기" if short_setup else "주봉 상승·매수 조건 대기" if rising else "주봉 하락·매도 조건 대기")
        entry, label = (float(previous.high), "직전일 고가") if rising else (float(previous.low), "직전일 저가")
        zone = "낮은 구간" if k < 30 else "높은 구간" if k > 70 else "중간 구간"
        action = "넘어야 매수 조건이 확인됩니다" if rising else "아래로 내려가야 매도 조건이 확인됩니다"
        detail = (f"주봉의 가격 힘은 {'강해지는 중' if rising else '약해지는 중'}이고, 일봉 과열·침체 지표는 "
                  f"{k:.1f}로 {zone}입니다. 가격이 {label} {entry:,.0f}원을 {action}.")
        levels = (("price", entry, f"엘더 {label}"), ("stochastic", 30.0, "매수 관심 30"), ("stochastic", 70.0, "매도 관심 70"))
        return self._item(name, state, detail, levels=levels)
