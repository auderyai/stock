"""Compatibility entry point for the layered PySide6 featured-research UI."""
from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from krx_research.database import resolve_database_target
from krx_research.qt.controllers.featured_controller import FeaturedResearchController
from krx_research.qt.services.featured_service import FeaturedResearchService
from krx_research.qt.windows.featured_window import FeaturedResearchView
from krx_research.ui.data import WorkstationData


class FeaturedResearchWindow(FeaturedResearchView):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=Path(__file__).resolve().parents[3]
        self._chart_data=WorkstationData(resolve_database_target(root,read_only=True))
        self.controller=FeaturedResearchController(self,FeaturedResearchService(),self._chart_data,parent=self)
        self.controller.initialize()


def launch_featured_research()->int:
    app=QApplication.instance() or QApplication(sys.argv); w=FeaturedResearchWindow(); w.show(); return int(app.exec() or 0)
