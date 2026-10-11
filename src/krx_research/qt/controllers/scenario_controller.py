from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from krx_research.qt.presentation.error_presenter import user_friendly_error
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research.qt.workers.task_runner import TaskRunner


class ScenarioController(QObject):
    """Coordinates scenario inputs, async calculation and PySide6 presentation."""

    def __init__(self, view, service, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.service = service
        self.runner = TaskRunner(self)
        self.error_log = ErrorLogService()
        view.runRequested.connect(self.run)
        view.indicatorViewRequested.connect(self.view.show_indicator)

    def initialize(self) -> None:
        try:
            current = self.service.current_features(self.view.daily)
            self.view.set_current_features(current)
        except Exception as exc:
            self._show_error(str(exc))

    def run(self) -> None:
        try:
            request = self.service.build_request(
                self.view.daily,
                self.view.market,
                *self.view.request_values(),
            )
        except Exception as exc:
            QMessageBox.critical(self.view, "입력 오류", str(exc))
            return
        self.view.set_busy(True, "과거 일봉으로 시간순 검증과 전체 지표 경로를 계산 중…")
        self.runner.submit(
            lambda: self.service.calculate(self.view.daily.copy(deep=True), request),
            on_result=lambda result: self._ready(result, request.indicator),
            on_error=self._error,
        )

    def _ready(self, result, selected_indicator: str) -> None:
        self.view.set_busy(False)
        self.view.set_analysis(result, selected_indicator)

    def _error(self, trace: str) -> None:
        self.view.set_busy(False)
        path = self.error_log.write(trace)
        message = user_friendly_error(trace)
        if path:
            message += f"\n\n오류 로그: {path}"
        QMessageBox.critical(self.view, "시나리오 계산 오류", message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self.view, "보조지표 시나리오", message)
