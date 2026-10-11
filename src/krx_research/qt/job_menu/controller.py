from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from krx_research.application.job_menu.models import JobRequest, LegacyJobSpec
from krx_research.application.job_menu.service import Menu257ApplicationService
from krx_research.infrastructure.job_menu import PythonJobExecutor
from .worker import JobWorker


class JobMenuController(QObject):
    progress = Signal(str)
    status_changed = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, project_root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._executor = PythonJobExecutor(project_root)
        self._service = Menu257ApplicationService(self._executor)
        self._thread: QThread | None = None
        self._worker: JobWorker | None = None

    def run(self, request: JobRequest) -> None:
        self._start(JobWorker(self._service, request=request))

    def run_legacy(self, spec: LegacyJobSpec) -> None:
        self._start(JobWorker(self._service, legacy=spec))

    def cancel(self) -> None:
        self.status_changed.emit("중지 요청 중...")
        self._service.cancel()

    def _start(self, worker: JobWorker) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.failed.emit("이미 다른 작업이 실행 중입니다.")
            return
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.succeeded.connect(lambda result: self.completed.emit(
            f"{result.summary}\n로그: {result.log_path}"
        ))
        worker.failed.connect(self.failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_finished)
        self._thread = thread
        self._worker = worker
        self.busy_changed.emit(True)
        self.status_changed.emit("실행 중...")
        thread.start()

    def _on_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.busy_changed.emit(False)
        self.status_changed.emit("대기")
