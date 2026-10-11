from __future__ import annotations

import pandas as pd

from krx_research_nextgen.models.chart_data import ChartBundle, IndicatorConfig, TIMEFRAME_LABELS, TIMEFRAME_RULES
from krx_research_nextgen.services.classic_strategy_service import ClassicStrategyService
from krx_research_nextgen.services.technical_analysis_service import TechnicalAnalysisService


class ChartService:
    """Qt-free chart application service.

    It receives already-loaded OHLCV data and prepares a render-ready ChartBundle.
    DB access is intentionally not part of this service in Stage 1.
    """

    def __init__(self, technical_analysis: TechnicalAnalysisService | None = None, classic_strategy: ClassicStrategyService | None = None) -> None:
        self._technical_analysis = technical_analysis or TechnicalAnalysisService()
        self._classic_strategy = classic_strategy or ClassicStrategyService()

    def prepare(
        self,
        symbol: str,
        frame: pd.DataFrame,
        config: IndicatorConfig | None = None,
        timeframe: str = "D",
        investor_flow: pd.DataFrame | None = None,
        display_limit: int | None = None,
    ) -> ChartBundle:
        selected, assessments = timeframe.strip().upper(), self._classic_strategy.assess(frame)
        if selected not in TIMEFRAME_LABELS:
            raise ValueError(f"Unsupported chart timeframe: {timeframe}")
        if selected != "D":
            rule = TIMEFRAME_RULES[selected]
            frame = frame.resample(rule).agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna(subset=["open", "high", "low", "close"])
            if investor_flow is not None and not investor_flow.empty:
                investor_flow = investor_flow.resample(rule).sum(min_count=1)
        if investor_flow is not None and not investor_flow.empty:
            investor_flow = investor_flow.sort_index().loc[frame.index.min():frame.index.max()].dropna(how="all")
        enriched = self._technical_analysis.enrich(frame, config=config)
        if display_limit:
            enriched = enriched.tail(max(1, int(display_limit)))
            if investor_flow is not None and not investor_flow.empty:
                investor_flow = investor_flow.loc[enriched.index.min():enriched.index.max()]
        return ChartBundle(symbol=symbol, frame=enriched, investor_flow=investor_flow if investor_flow is not None else pd.DataFrame(), assessments=assessments)
