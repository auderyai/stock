"""Compatibility entry point for the layered PySide6 theme-research UI."""
from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
from krx_research.qt.application.compatibility_factory import theme_controller
from krx_research.qt.windows.theme_window import ThemeResearchView


class ThemeResearchWindow(ThemeResearchView):
    def __init__(self,parent=None):
        super().__init__(parent)
        self._chart_data,self.controller=theme_controller(self)
        self.controller.initialize()


def launch_theme_research()->int:
    app=QApplication.instance() or QApplication(sys.argv); w=ThemeResearchWindow(); w.show(); return int(app.exec() or 0)
