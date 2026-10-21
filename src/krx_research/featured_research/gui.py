"""Compatibility entry point for the layered PySide6 featured-research UI."""
from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
from krx_research.qt.application.compatibility_factory import featured_controller
from krx_research.qt.windows.featured_window import FeaturedResearchView


class FeaturedResearchWindow(FeaturedResearchView):
    def __init__(self,parent=None):
        super().__init__(parent)
        self._chart_data,self.controller=featured_controller(self)
        self.controller.initialize()


def launch_featured_research()->int:
    app=QApplication.instance() or QApplication(sys.argv); w=FeaturedResearchWindow(); w.show(); return int(app.exec() or 0)
