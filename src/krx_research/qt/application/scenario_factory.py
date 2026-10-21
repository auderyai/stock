from __future__ import annotations

from krx_research.database.scenario_market import ScenarioMarketRepository
from krx_research.qt.controllers.scenario_controller import ScenarioController
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.services.scenario_service import ScenarioService


def scenario_controller(view):
    """Build the indicator-scenario controller without loading other Qt features."""
    return ScenarioController(
        view,
        ScenarioService(ScenarioMarketRepository()),
        ErrorLogService(),
        parent=view,
    )


__all__ = ["scenario_controller"]
