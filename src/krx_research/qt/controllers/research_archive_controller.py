from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.presentation.error_presenter import user_friendly_error
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.workers.task_runner import TaskRunner


class ResearchArchiveController(QObject):
    def __init__(self, view, service, chart_service, parent=None):
        super().__init__(parent or view)
        self.view, self.service, self.chart_service = view, service, chart_service
        self.runner, self.logs, self.children = TaskRunner(self), ErrorLogService(), []
        view.queryRequested.connect(self.query)
        view.importRequested.connect(self.import_files)
        view.chartRequested.connect(self.open_chart)

    def initialize(self) -> None:
        today = date.today()
        self.view.set_period(today - timedelta(days=365), today)
        self.runner.submit(self.service.initialize, on_error=self._error)

    def query(self, start, end, search="") -> None:
        self.runner.submit(
            lambda: self.service.query(start, end, search),
            on_result=lambda frame: self.view.set_frame(frame, f"{start} ~ {end}: {len(frame):,}건"),
            on_error=self._error,
        )

    def import_files(self, files) -> None:
        def done(results):
            QMessageBox.information(self.view, "등록 완료", f"{len(results):,}개 원본을 검증·보관했습니다.")
            self.query(self.view.start.date().toPython(), self.view.end.date().toPython(), self.view.search.text())
        self.runner.submit(lambda: self.service.import_files(files), on_result=done, on_error=self._error)

    def open_chart(self, ticker: str) -> None:
        window = ChartWindow(self.chart_service, ticker, parent=self.view)
        self.children.append(window)
        window.destroyed.connect(lambda _=None, w=window: self.children.remove(w) if w in self.children else None)
        window.show()

    def _error(self, trace: str) -> None:
        path = self.logs.write(trace)
        message = user_friendly_error(trace) + (f"\n\n오류 로그: {path}" if path else "")
        QMessageBox.critical(self.view, "연구자료 오류", message)
