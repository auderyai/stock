"""Compatibility facade that wires the layered Qt chart view/controller."""
from __future__ import annotations

import pandas as pd

from krx_research.qt.controllers.chart_controller import ChartController
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.windows.chart_window import ChartWindow as _ChartView


class ChartWindow(_ChartView):
    def __init__(
        self,
        chart_service_or_data,
        ticker: str,
        *,
        quote_venue: str = "KRX",
        parent=None,
        navigation_enabled: bool = False,
        navigation_frame: pd.DataFrame | None = None,
        navigation_labels: dict[str, str] | None = None,
    ):
        service = chart_service_or_data
        if not isinstance(service, ChartService):
            service = ChartService(service)
        super().__init__(ticker, quote_venue=quote_venue, navigation_enabled=navigation_enabled, parent=parent)
        self.controller = ChartController(self, service, ErrorLogService(), parent=self)
        if navigation_enabled and navigation_frame is not None:
            self.set_navigation_results(navigation_frame, navigation_labels or {}, selected_ticker=ticker)
        self.controller.load()

    def set_ticker(self, ticker: str, quote_venue: str | None = None) -> None:
        self.controller.set_ticker(ticker, quote_venue)


__all__ = ["ChartWindow"]
