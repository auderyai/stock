from __future__ import annotations
import traceback
from typing import Any, Callable
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()

class TaskWorker(QRunnable):
    """Generic QRunnable. Business code is injected and remains Qt-free."""
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self._fn = fn
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self._fn())
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()

class TaskRunner(QObject):
    """Owns worker lifetime and thread-pool interaction for one controller."""
    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None):
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        self._workers: set[TaskWorker] = set()

    def submit(self, fn: Callable[[], Any], *, on_result=None, on_error=None, on_finished=None) -> TaskWorker:
        worker = TaskWorker(fn)
        self._workers.add(worker)
        if on_result is not None:
            worker.signals.result.connect(on_result)
        if on_error is not None:
            worker.signals.error.connect(on_error)
        if on_finished is not None:
            worker.signals.finished.connect(on_finished)
        worker.signals.finished.connect(lambda w=worker: self._workers.discard(w))
        self._pool.start(worker)
        return worker
