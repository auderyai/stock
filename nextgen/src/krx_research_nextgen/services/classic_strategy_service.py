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
                return self._item(name, f"{direction} 충격 5파 후보", "확정 스윙이 파동2의 100% 초과 되돌림 금지, 파동3 최단 금지, 파동4·파동1 영역 비중첩 규칙을 충족합니다. 파동 차수와 향후 진행은 확정하지 않습니다.", labels)
        return self._item(name, "유효 충격파 미확인", "최근 확정 스윙에서 엘리어트 충격파의 세 가지 필수 규칙을 모두 충족하는 연속 5파를 찾지 못했습니다.")

    def _livermore(self, daily: pd.DataFrame) -> StrategyAssessment:
        name = "제시 리버모어"
        if len(daily) < 253: return self._item(name, "자료부족", "당일을 제외한 252거래일 피벗과 직전 20일 거래량 판정에는 최소 253거래일이 필요합니다.")
        last, prior = daily.iloc[-1], daily.iloc[-253:-1]
        pivot, average = float(prior.high.max()), float(prior.volume.tail(20).mean())
        ratio = float(last.volume) / average if average > 0 else np.nan
        breakout, heavy = float(last.close) > pivot, np.isfinite(ratio) and ratio >= 1.5
        state = ("신고가·거래량 확인" if breakout and heavy else "신고가 돌파·거래량 미확인" if breakout else
                 "피벗 돌파 대기" if float(last.close) >= pivot * .97 else "피벗 대기")
        detail = f"직전 252거래일 피벗 {pivot:,.0f}, 종가 {last.close:,.0f}, 당일 제외 직전 20일 평균 대비 거래량 {ratio:.2f}배입니다. 확대 거래량의 운영 기준은 1.50배이며 시장·업종 확인은 별도입니다."
        return self._item(name, state, detail, levels=(("price", pivot, "리버모어 피벗"), ("volume", average, "직전 20일 평균 거래량")))

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
        state = ("매수 진입 확인" if long_entry else "매수 관심 구간" if long_setup else "매도 진입 확인" if short_entry else
                 "매도 관심 구간" if short_setup else "주봉 상승·일봉 대기" if rising else "주봉 하락·일봉 대기")
        entry, label = (float(previous.high), "직전일 고가") if rising else (float(previous.low), "직전일 저가")
        detail = f"주봉 MACD-Histogram은 {'상승' if rising else '하락'}, 일봉 Slow %K는 {k:.1f}입니다. {'매수' if rising else '매도'} 진입 기준은 {label} {entry:,.0f} 돌파입니다."
        levels = (("price", entry, f"엘더 {label}"), ("stochastic", 30.0, "매수 관심 30"), ("stochastic", 70.0, "매도 관심 70"))
        return self._item(name, state, detail, levels=levels)
