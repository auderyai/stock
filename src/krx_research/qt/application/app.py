from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from krx_research.qt.application.window_factory import AuxiliaryWindowFactory
from krx_research.qt.controllers.workstation_controller import WorkstationController
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.export_service import ExcelExportService
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.services.screening_service import ScreeningService
from krx_research.qt.services.security_search_service import SecuritySearchService
from krx_research.qt.services.assistant_service import AssistantService
from krx_research.qt.windows.workstation_window import WorkstationWindow
from krx_research.data_engine.workstation_repository import WorkstationData
from krx_research.database.settings import resolve_database_target


class NewStockApplication:
    """Composition root for the PySide6/PostgreSQL desktop application."""

    def __init__(self, database_target):
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName("KRX Stock")

        self.data = WorkstationData(database_target)
        self.screening = ScreeningService(self.data)
        self.chart_service = ChartService(self.data)
        self.security_search = SecuritySearchService(self.data)
        self.exporter = ExcelExportService()
        self.assistant = AssistantService(database_target)
        write_target = resolve_database_target(Path(__file__).resolve().parents[4])
        self.window_factory = AuxiliaryWindowFactory(self.data, self.chart_service, write_target)

        self.window = WorkstationWindow()
        self.controller = WorkstationController(
            self.window,
            self.screening,
            self.chart_service,
            self.exporter,
            self.security_search,
            self.window_factory,
            self.assistant,
            ErrorLogService(),
        )

    def run(self) -> int:
        self.controller.initialize()
        self.window.show()
        return int(self.qt_app.exec() or 0)


def launch(database_target) -> int:
    return NewStockApplication(database_target).run()
