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

    @staticmethod
    def _elliott_detail(points, direction: str) -> str:
        prices = [point[1] for point in points]
        p0, p1, p2, p3, p4, p5 = prices
        lengths = {1: abs(p1 - p0), 3: abs(p3 - p2), 5: abs(p5 - p4)}
        retrace2 = abs(p2 - p1) / lengths[1] * 100
        retrace4 = abs(p4 - p3) / lengths[3] * 100
        wave2_margin = p2 - p0 if direction == "상승" else p0 - p2
        overlap_margin = p4 - p1 if direction == "상승" else p1 - p4
        fifth_margin = p5 - p3 if direction == "상승" else p3 - p5
        turns = " → ".join(
            f"{'시작' if index == 0 else f'{index}파 끝'} {date:%Y-%m-%d} {price:,.0f}원"
            for index, (date, price, _) in enumerate(points)
        )
        roles = ("상위 상승 추세의 동인파 또는 상위 하락 추세 조정의 A파나 C파에 해당할 수 있습니다." if direction == "상승" else
                 "현재 구간은 A파 또는 C파 내부 후보입니다. A파라면 이후 B파 반등과 C파 하락이 남아 있고, "
                 "C파라면 앞선 A파와 B파를 추가로 확인해야 합니다.")
        abc = ("" if direction == "상승" else
               "A-B-C 조정 관점: A파는 첫 하락, B파는 반등, C파는 두 번째 하락입니다. "
               "A파와 C파는 내부적으로 작은 동인 구조를 가질 수 있습니다.\n")
        layout_title = "파동 배치" if direction == "상승" else "A/C 내부 소파동 배치"
        fifth_title = "5파 위치" if direction == "상승" else "내부 마지막 소파동 위치"
        conclusion = ("세 가지 필수 가격 규칙을 통과한 상승 동인 5파 후보일 뿐, 완성파·반전·향후 방향을 확정하지 않습니다." if direction == "상승" else
                      "A파 또는 C파 내부 구조의 기본 가격 규칙을 통과한 후보일 뿐, A-B-C 위치·조정 완료·반전을 확정하지 않습니다.")
        fifth = (f"3파 끝을 {abs(fifth_margin):,.0f}원 넘어 새 극값 형성" if fifth_margin > 0 else
                 f"3파 끝을 넘지 못한 절단 5파 가능성({abs(fifth_margin):,.0f}원 차이)")
        return (f"확인 구간: {points[0][0]:%Y-%m-%d} ~ {points[-1][0]:%Y-%m-%d}\n"
                f"{layout_title}: {turns}\n"
                f"① 2파 규칙: 1파 시작점을 넘지 않음, 여유 {wave2_margin:,.0f}원 → 통과\n"
                f"② 3파 규칙: 1파 {lengths[1]:,.0f}원, 3파 {lengths[3]:,.0f}원, "
                f"5파 {lengths[5]:,.0f}원; 가장 짧은 파동은 {min(lengths, key=lengths.get)}파 → 통과\n"
                f"③ 4파 규칙: 1파 가격 영역과 겹치지 않음, 여유 {overlap_margin:,.0f}원 → 통과\n"
                f"④ 되돌림 참고값: 2파는 1파의 {retrace2:.1f}%, 4파는 3파의 {retrace4:.1f}%\n"
                f"⑤ {fifth_title}: {fifth}\n"
                f"{abc}"
                f"상위 파동 역할: 미확정. {roles}\n"
                "아직 확인하지 못한 항목: 1·3·5파 내부의 5개 세부파동, 2·4파 내부의 3개 세부파동, "
                "파동 차수, 조정 형태와 대안 파동 수.\n"
                f"최종 해석: {conclusion}")

    @staticmethod
    def _elliott_state(direction: str) -> str:
        return ("하락 조정 A파 또는 C파 후보·상위 구조 미확정" if direction == "하락" else
                "상승 동인 5파 후보·상위 차수 미확정")

    def _elliott(self, daily: pd.DataFrame) -> StrategyAssessment:
        name = "엘리어트 파동"; swings = self._swings(daily)
        for end in range(len(swings), 5, -1):
            points, direction = swings[end - 6:end], self._impulse(swings[end - 6:end])
            if direction:
                labels = tuple((date, price,
                                ("A/C 시작" if index == 0 else f"A/C-{index}") if direction == "하락"
                                else "시작" if index == 0 else str(index))
                               for index, (date, price, _) in enumerate(points))
                return self._item(name, self._elliott_state(direction),
                                  self._elliott_detail(points, direction), labels)
        return self._item(name, "동인 5파 기본규칙 미충족",
                          "검사 범위: 최근 확정된 고점과 저점을 6개씩 묶어 동인 5파의 세 가지 필수 가격 규칙을 확인했습니다.\n"
                          "결과: 세 규칙을 동시에 만족하는 상승 또는 하락 동인 5파 후보를 찾지 못했습니다.\n"
                          "해석 제한: 조정파는 3파 또는 그 조합이며 별도의 내부 구조 분석이 필요합니다. 이 결과만으로 파동이 없다고 단정할 수 없습니다.")

    def _livermore(self, daily: pd.DataFrame) -> StrategyAssessment:
        name = "제시 리버모어"
        if len(daily) < 253: return self._item(name, "자료부족", "당일을 제외한 252거래일 피벗과 직전 20일 거래량 판정에는 최소 253거래일이 필요합니다.")
        last, prior = daily.iloc[-1], daily.iloc[-253:-1]
        pivot, average = float(prior.high.max()), float(prior.volume.tail(20).mean())
        pivot_date = prior.high.idxmax()
        ratio = float(last.volume) / average if average > 0 else np.nan
        breakout, heavy = float(last.close) > pivot, np.isfinite(ratio) and ratio >= 1.5
        state = ("최고가 돌파·거래량 증가" if breakout and heavy else "최고가 돌파·거래량 부족" if breakout else
                 "최고가에 가까움·돌파 대기" if float(last.close) >= pivot * .97 else "최고가 돌파 전")
        gap = float(last.close) - pivot
        price_result = "통과" if breakout else "미통과"
        volume_result = "통과" if heavy else "미통과"
        conclusion = ("가격과 거래량 조건을 모두 만족했습니다." if breakout and heavy else
                      "가격은 돌파했지만 거래량 증가 조건이 부족합니다." if breakout else
                      "거래량은 증가했지만 가격이 최근 1년 최고가를 돌파하지 못했습니다." if heavy else
                      "가격과 거래량 조건을 모두 만족하지 못했습니다.")
        detail = (f"계산 기준일: {daily.index[-1]:%Y-%m-%d}\n"
                  f"① 가격 조건: 종가 {last.close:,.0f}원 > 직전 252거래일 최고가 {pivot:,.0f}원"
                  f"({pivot_date:%Y-%m-%d}) → {price_result}\n"
                  f"   차이: {abs(gap):,.0f}원, 최고가 대비 {abs(gap) / pivot * 100:.1f}% "
                  f"{'높음' if gap > 0 else '낮음'}\n"
                  f"② 거래량 조건: 오늘 {last.volume:,.0f}주 ÷ 직전 20일 평균 {average:,.0f}주 = "
                  f"{ratio:.2f}배, 필요 기준 1.50배 이상 → {volume_result}\n"
                  f"최종 해석: {conclusion}\n"
                  "참고: 시장 전체와 업종의 강도는 이 판정에 포함하지 않습니다.")
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
        prior_hist, current_hist = float(histogram.iloc[-2]), float(histogram.iloc[-1])
        rising, k = current_hist > prior_hist, float(stochastic.iloc[-1].slow_k)
        last, previous = daily.iloc[-1], daily.iloc[-2]
        long_setup, short_setup = rising and k < 30, not rising and k > 70
        price_cross = last.high > previous.high if rising else last.low < previous.low
        long_entry, short_entry = long_setup and price_cross, short_setup and price_cross
        state = ("매수 조건 충족" if long_entry else "매수 관심·가격 돌파 대기" if long_setup else "매도 조건 충족" if short_entry else
                 "매도 관심·가격 하락 대기" if short_setup else "주봉 상승·매수 조건 대기" if rising else "주봉 하락·매도 조건 대기")
        entry, label = (float(previous.high), "직전일 고가") if rising else (float(previous.low), "직전일 저가")
        setup = long_setup if rising else short_setup
        trigger = long_entry if rising else short_entry
        daily_value = float(last.high if rising else last.low)
        oscillator_rule = "30 미만" if rising else "70 초과"
        price_rule = ">" if rising else "<"
        detail = (f"계산 기준일: {daily.index[-1]:%Y-%m-%d}\n"
                  f"① 주봉 방향: MACD 힘 지표가 {prior_hist:,.2f}에서 {current_hist:,.2f}로 "
                  f"{'상승' if rising else '하락'} → {'매수' if rising else '매도'} 방향 확인\n"
                  f"② 일봉 시점: 과열·침체 지표 {k:.1f}, 필요 기준 {oscillator_rule} → "
                  f"{'통과' if setup else '미통과'}\n"
                  f"③ 가격 확인: 오늘 {'고가' if rising else '저가'} {daily_value:,.0f}원 {price_rule} "
                  f"{label} {entry:,.0f}원 → {'통과' if price_cross else '미통과'}\n"
                  f"최종 해석: {'세 조건이 모두 맞아 진입 조건이 확인되었습니다.' if trigger else '아직 세 조건이 모두 맞지 않아 진입 신호가 아닙니다.'}\n"
                  "주의: 세 조건의 순서를 확인하는 규칙이며 수익을 보장하거나 자동 매매를 지시하지 않습니다.")
        levels = (("price", entry, f"엘더 {label}"), ("stochastic", 30.0, "매수 관심 30"), ("stochastic", 70.0, "매도 관심 70"))
        return self._item(name, state, detail, levels=levels)
