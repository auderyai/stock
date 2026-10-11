"""Compatibility entry point for the layered PySide6 theme-research UI."""
from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from krx_research.database import resolve_database_target
from krx_research.qt.controllers.theme_controller import ThemeResearchController
from krx_research.qt.services.theme_service import ThemeResearchService
from krx_research.qt.windows.theme_window import ThemeResearchView
from krx_research.ui.data import WorkstationData


class ThemeResearchWindow(ThemeResearchView):
    def __init__(self,parent=None):
        super().__init__(parent)
        root=Path(__file__).resolve().parents[3]
        self._chart_data=WorkstationData(resolve_database_target(root,read_only=True))
        self.controller=ThemeResearchController(self,ThemeResearchService(),self._chart_data,parent=self)
        self.controller.initialize()


def launch_theme_research()->int:
    app=QApplication.instance() or QApplication(sys.argv); w=ThemeResearchWindow(); w.show(); return int(app.exec() or 0)
