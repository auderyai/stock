"""Compatibility facade for the layered PySide6 indicator-scenario window."""
from __future__ import annotations

from krx_research.database.scenario_market import ScenarioMarketRepository
from krx_research.qt.controllers.scenario_controller import ScenarioController
from krx_research.qt.services.scenario_service import ScenarioService
from krx_research.qt.windows.scenario_window import ScenarioWindow as _ScenarioView


class ScenarioWindow(_ScenarioView):
    def __init__(self, daily, ticker: str = "", market: str = "", parent=None):
        super().__init__(daily, ticker, market, parent)
        self.controller = ScenarioController(
            self,
            ScenarioService(ScenarioMarketRepository()),
            parent=self,
        )
        self.controller.initialize()


def open_scenario_window(parent, daily, ticker: str = "", market: str = ""):
    window = ScenarioWindow(daily, ticker, market, parent)
    window.show()
    return window


__all__ = ["ScenarioWindow", "open_scenario_window"]
