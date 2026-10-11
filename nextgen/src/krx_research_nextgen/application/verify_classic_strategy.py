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
    assert service.assess(frame(252))[1].state == "자료부족"
    data = frame(253); data.iloc[-1] = [240, 300, 235, 250, 2_000]
    results = service.assess(data)
    assert results[1].state == "신고가·거래량 확인" and "2.00배" in results[1].detail
    assert {level[0] for level in results[1].levels} == {"price", "volume"}
    assert {level[0] for level in results[2].levels} == {"price", "stochastic"}
    assert "+" not in "\n".join(result.text() for result in results)
    for timeframe in ("D", "W", "M", "Q", "Y"):
        bundle = ChartService().prepare("TEST", data, timeframe=timeframe, display_limit=10)
        assert len(bundle.frame) <= 10 and len(bundle.assessments) == 3
    print("CLASSIC_STRATEGY_TEST_OK")


if __name__ == "__main__": main()
