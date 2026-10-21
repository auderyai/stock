from __future__ import annotations

from pathlib import Path

from krx_research.data_engine.workstation_repository import WorkstationData
from krx_research.database import resolve_database_target
from krx_research.qt.application.scenario_factory import scenario_controller
from krx_research.qt.controllers.featured_controller import FeaturedResearchController
from krx_research.qt.controllers.investor_dashboard_controller import InvestorDashboardController
from krx_research.qt.controllers.theme_controller import ThemeResearchController
from krx_research.qt.repositories.investor_flow_repository import InvestorFlowRepository
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.featured_service import FeaturedResearchService
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.services.investor_dashboard_service import InvestorDashboardService
from krx_research.qt.services.theme_service import ThemeResearchService


def default_workstation_data() -> WorkstationData:
    root = Path(__file__).resolve().parents[4]
    return WorkstationData(resolve_database_target(root, read_only=True))


def featured_controller(view, data: WorkstationData | None = None):
    source = data or default_workstation_data()
    return source, FeaturedResearchController(
        view, FeaturedResearchService(), ChartService(source), ErrorLogService(), parent=view
    )


def theme_controller(view, data: WorkstationData | None = None):
    source = data or default_workstation_data()
    return source, ThemeResearchController(
        view, ThemeResearchService(), ChartService(source), ErrorLogService(), parent=view
    )


def investor_controller(view, data: WorkstationData):
    on_demand = data._on_demand
    if on_demand is None:
        raise ValueError("PostgreSQL 연결이 필요합니다.")
    return InvestorDashboardController(
        view,
        InvestorDashboardService(InvestorFlowRepository(on_demand.settings)),
        ChartService(data),
        parent=view,
    )
