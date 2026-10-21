from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from krx_research.qt.controllers.featured_controller import FeaturedResearchController
from krx_research.qt.controllers.investor_dashboard_controller import InvestorDashboardController
from krx_research.qt.controllers.market_index_controller import MarketIndexController
from krx_research.qt.controllers.theme_controller import ThemeResearchController
from krx_research.qt.services.featured_service import FeaturedResearchService
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.services.investor_dashboard_service import InvestorDashboardService
from krx_research.qt.services.market_index_service import MarketIndexService
from krx_research.qt.repositories.market_index_repository import MarketIndexRepository
from krx_research.qt.repositories.investor_flow_repository import InvestorFlowRepository
from krx_research.qt.services.theme_service import ThemeResearchService
from krx_research.qt.windows.featured_window import FeaturedResearchView
from krx_research.qt.windows.investor_dashboard_window import InvestorDashboardView
from krx_research.qt.windows.market_index_window import MarketIndexView
from krx_research.qt.windows.theme_window import ThemeResearchView
from krx_research.qt.windows.research_archive_window import ResearchArchiveView
from krx_research.qt.controllers.research_archive_controller import ResearchArchiveController
from krx_research.research_archive import ResearchArchiveService


@dataclass(slots=True)
class ManagedWindow:
    view: object
    controller: object


class AuxiliaryWindowFactory:
    """Composition service for secondary PySide6 windows.

    WorkstationController only orchestrates user actions; concrete View,
    Controller and Service wiring stays out of the controller and legacy
    compatibility facades are never imported by the main application path.
    """

    def __init__(self, workstation_data, chart_service, database_target):
        self._data = workstation_data
        self._chart_service = chart_service
        self._database_target = database_target

    def investor(self, parent, start: dt.date, end: dt.date, *, navigate: bool) -> ManagedWindow:
        on_demand = self._data._on_demand
        if on_demand is None:
            raise ValueError("PostgreSQL 연결이 필요합니다.")
        view = InvestorDashboardView(parent=parent, start=start, end=end)
        controller = InvestorDashboardController(
            view,
            InvestorDashboardService(InvestorFlowRepository(on_demand.settings)),
            self._chart_service,
            navigate=navigate,
            parent=view,
        )
        controller.initialize()
        return ManagedWindow(view=view, controller=controller)

    def market_index(self, parent, *, navigate: bool) -> ManagedWindow:
        view = MarketIndexView(parent=parent, navigate=navigate)
        on_demand = self._data._on_demand
        if on_demand is None:
            raise ValueError("PostgreSQL 연결이 필요합니다.")
        service = MarketIndexService(MarketIndexRepository(on_demand.settings))
        controller = MarketIndexController(view, service, parent=view)
        controller.initialize()
        return ManagedWindow(view=view, controller=controller)

    def featured(self, parent) -> ManagedWindow:
        view = FeaturedResearchView(parent=parent)
        controller = FeaturedResearchController(
            view, FeaturedResearchService(), self._chart_service, ErrorLogService(), parent=view
        )
        controller.initialize()
        return ManagedWindow(view=view, controller=controller)

    def theme(self, parent) -> ManagedWindow:
        view = ThemeResearchView(parent=parent)
        controller = ThemeResearchController(
            view, ThemeResearchService(), self._chart_service, ErrorLogService(), parent=view
        )
        controller.initialize()
        return ManagedWindow(view=view, controller=controller)

    def research_archive(self, parent) -> ManagedWindow:
        view = ResearchArchiveView(parent=parent)
        controller = ResearchArchiveController(
            view, ResearchArchiveService(self._database_target), self._chart_service,
            ErrorLogService(), parent=view
        )
        controller.initialize()
        return ManagedWindow(view=view, controller=controller)
