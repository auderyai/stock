import numpy as np
import pandas as pd

from krx_research_nextgen.services.chart_service import ChartService
from krx_research_nextgen.services.classic_strategy_service import ClassicStrategyService


def frame(size: int) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=size)
    close = pd.Series(np.linspace(100, 200, size), index=index)
    return pd.DataFrame({"open": close * .99, "high": close * 1.01, "low": close * .98,
                         "close": close, "volume": 1_000.0}, index=index)


def main() -> None:
    service = ClassicStrategyService()
    assert service._impulse([(0, 10, "L"), (1, 20, "H"), (2, 15, "L"), (3, 35, "H"), (4, 25, "L"), (5, 40, "H")]) == "상승"
    assert service._impulse([(0, 10, "L"), (1, 20, "H"), (2, 9, "L"), (3, 35, "H"), (4, 25, "L"), (5, 40, "H")]) is None
    down = list(zip(pd.bdate_range("2026-05-27", periods=6),
                    (2545, 1714, 2075, 1423, 1710, 1415), "HLHLHL", strict=True))
    assert service._impulse(down) == "하락"
    current = frame(20)
    assert service._elliott_current_state(down, "하락", current).endswith("하락 연장 확인 중")
    down_detail = service._elliott_detail(down, "하락", current)
    assert all(text in down_detail for text in ("1파 831원", "3파 652원", "5파 295원",
                                                 "A-B-C 조정 관점", "A파는 첫 하락", "B파는 반등",
                                                 "C파는 두 번째 하락", "상위 파동 역할: 미확정",
                                                 "최근 기준일:", "현재 상황:"))
    old_valid = list(zip(pd.bdate_range("2025-01-02", periods=6),
                         (10, 20, 15, 35, 25, 40), "LHLHLH", strict=True))
    latest_invalid = list(zip(pd.bdate_range("2026-01-02", periods=6),
                              (30, 40, 20, 45, 15, 44), "LHLHLH", strict=True))
    service._swings = lambda _daily: old_valid + latest_invalid
    recent = service._elliott(frame(40))
    assert recent.state == "최근 기준일 파동 규칙 미충족"
    assert "과거에 끝난 유효 구간으로 대신 판정하지 않았습니다" in recent.detail
    service = ClassicStrategyService()
    assert service.assess(frame(252))[1].state == "자료부족"
    data = frame(253); data.iloc[-1] = [240, 300, 235, 250, 2_000]
    results = service.assess(data)
    assert results[1].state == "최고가 돌파·거래량 증가" and "2.00배" in results[1].detail
    assert "직전 252거래일 최고가" in results[1].detail
    assert {level[0] for level in results[1].levels} == {"price", "volume"}
    assert {level[0] for level in results[2].levels} == {"price", "stochastic"}
    explanations = "\n".join(result.text() for result in results)
    assert "현재 판단:" in explanations
    assert ("2파 규칙:" in results[0].detail or "검사 범위:" in results[0].detail)
    assert "가격 조건:" in results[1].detail and "주봉 방향:" in results[2].detail
    assert "+" not in explanations
    for timeframe in ("D", "W", "M", "Q", "Y"):
        bundle = ChartService().prepare("TEST", data, timeframe=timeframe, display_limit=10)
        assert len(bundle.frame) <= 10 and len(bundle.assessments) == 3
    print("CLASSIC_STRATEGY_TEST_OK")


if __name__ == "__main__": main()
