"""Compatibility facade for the layered PySide6 indicator-scenario window."""
from __future__ import annotations

from krx_research.qt.application.scenario_factory import scenario_controller
from krx_research.qt.windows.scenario_window import ScenarioWindow as _ScenarioView


class ScenarioWindow(_ScenarioView):
    def __init__(self, daily, ticker: str = "", market: str = "", parent=None):
        super().__init__(daily, ticker, market, parent)
        self.controller = scenario_controller(self)
        self.controller.initialize()


def open_scenario_window(parent, daily, ticker: str = "", market: str = ""):
    window = ScenarioWindow(daily, ticker, market, parent)
    window.show()
    return window


__all__ = ["ScenarioWindow", "open_scenario_window"]
