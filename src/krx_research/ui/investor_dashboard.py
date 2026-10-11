"""Compatibility facade for the layered PySide6 investor dashboard."""
from __future__ import annotations

import datetime as dt

from krx_research.qt.controllers.investor_dashboard_controller import InvestorDashboardController
from krx_research.qt.models.investor_dashboard import InvestorDashboardData
from krx_research.qt.repositories.investor_flow_repository import InvestorFlowRepository
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.investor_dashboard_service import InvestorDashboardService
from krx_research.qt.windows.investor_dashboard_window import InvestorDashboardView


class InvestorDashboardWindow(InvestorDashboardView):
    def __init__(self, workstation_data, parent=None, start: dt.date | None = None, end: dt.date | None = None):
        super().__init__(parent, start=start, end=end)
        on_demand = workstation_data._on_demand
        if on_demand is None:
            raise ValueError("PostgreSQL 연결이 필요합니다.")
        self.controller = InvestorDashboardController(
            self,
            InvestorDashboardService(InvestorFlowRepository(on_demand.settings)),
            ChartService(workstation_data),
            parent=self,
        )
        self.controller.initialize()


__all__ = ["InvestorDashboardData", "InvestorDashboardWindow"]
