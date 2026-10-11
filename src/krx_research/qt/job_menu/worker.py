from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from krx_research.application.job_menu.models import JobRequest, LegacyJobSpec
from krx_research.application.job_menu.service import Menu257ApplicationService


class JobWorker(QObject):
    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, service: Menu257ApplicationService,
                 request: JobRequest | None = None,
                 legacy: LegacyJobSpec | None = None) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._legacy = legacy

    @Slot()
    def run(self) -> None:
        try:
            if self._legacy is not None:
                result = self._service.run_legacy(self._legacy, self.progress.emit)
            elif self._request is not None:
                result = self._service.run(self._request, self.progress.emit)
            else:
                raise RuntimeError("실행 요청이 없습니다.")
            if result.succeeded:
                self.succeeded.emit(result)
            else:
                self.failed.emit(f"{result.summary}\n로그: {result.log_path}")
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()
