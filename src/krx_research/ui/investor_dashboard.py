"""Compatibility facade for the layered PySide6 investor dashboard."""
from __future__ import annotations

import datetime as dt

from krx_research.qt.application.compatibility_factory import investor_controller
from krx_research.qt.models.investor_dashboard import InvestorDashboardData
from krx_research.qt.windows.investor_dashboard_window import InvestorDashboardView


class InvestorDashboardWindow(InvestorDashboardView):
    def __init__(self, workstation_data, parent=None, start: dt.date | None = None, end: dt.date | None = None):
        super().__init__(parent, start=start, end=end)
        self.controller = investor_controller(self, workstation_data)
        self.controller.initialize()


__all__ = ["InvestorDashboardData", "InvestorDashboardWindow"]
