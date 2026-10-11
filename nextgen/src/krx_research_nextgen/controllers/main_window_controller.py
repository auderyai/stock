from __future__ import annotations

from krx_research_nextgen.models.chart_data import ChartBundle, IndicatorConfig
from krx_research_nextgen.models.security import SecurityRecord
from krx_research_nextgen.services.market_chart_service import MarketChartService
from krx_research_nextgen.services.scenario_service import ScenarioService
from krx_research_nextgen.services.security_search_service import SecuritySearchService
from threading import RLock


class MainWindowController:
    def __init__(
        self,
        security_search: SecuritySearchService,
        market_chart: MarketChartService,
        scenario: ScenarioService | None = None,
    ) -> None:
        self._security_search = security_search
        self._market_chart = market_chart
        self._scenario = scenario or ScenarioService()
        self._search_lock, self._chart_lock = RLock(), RLock()

    def search_securities(self, keyword: str, limit: int = 300) -> list[SecurityRecord]:
        with self._search_lock:
            return self._security_search.search(keyword=keyword, limit=limit)

    def prepare_chart(self, stock_code: str, limit: int = 550, timeframe: str = "D") -> ChartBundle:
        with self._chart_lock:
            return self._market_chart.prepare_recent_chart(
                stock_code, limit=limit, config=IndicatorConfig(rsi_period=14.0), timeframe=timeframe,
            )

    def status(self) -> dict[str, object]:
        with self._chart_lock: status = self._market_chart.diagnostics()
        status["security_relation"] = self._security_search.source_relation
        return status

    def scenario_current(self, frame, indicator: str) -> float: return self._scenario.current_value(frame, indicator)
    def scenario_request(self, frame, indicator: str, target: str, horizon: str, lookback: str): return self._scenario.request(frame, indicator, target, horizon, lookback)
    def analyze_scenario(self, frame, request): return self._scenario.analyze(frame, request)
