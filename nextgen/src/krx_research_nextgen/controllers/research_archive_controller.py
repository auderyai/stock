from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research_nextgen.workers.task_runner import TaskRunner


class ResearchArchiveController(QObject):
    """Runs archive use cases and reports UI-ready outcomes."""

    initialized = pyqtSignal()
    imported = pyqtSignal(object)
    queried = pyqtSignal(object)
    failed = pyqtSignal(str, str, str)

    def __init__(self, service, error_log: ErrorLogService, parent=None):
        super().__init__(parent)
        self._service, self._logs = service, error_log
        self._tasks = TaskRunner(self)

    def initialize(self) -> None:
        self._submit("initialize", self._service.initialize, lambda _value: self.initialized.emit())

    def import_files(self, paths: list[str]) -> None:
        self._submit("import", lambda: self._service.import_files(paths), self.imported.emit)

    def query(self, start, end, search: str) -> None:
        self._submit("query", lambda: self._service.query(start, end, search), self.queried.emit)

    def _submit(self, operation: str, task, success) -> None:
        self._tasks.submit(
            task, on_result=success,
            on_error=lambda trace: self._report_error(operation, trace), channel=operation,
        )

    def _report_error(self, operation: str, trace: str) -> None:
        path = self._logs.write(str(trace))
        lines = [line.strip() for line in str(trace).splitlines() if line.strip()]
        message = next((line.split(":", 1)[1].strip() for line in reversed(lines)
                        if line.startswith(("RuntimeError:", "ValueError:"))), "알 수 없는 오류")
        self.failed.emit(operation, message, str(path or ""))
