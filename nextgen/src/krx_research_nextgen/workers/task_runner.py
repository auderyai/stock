from __future__ import annotations

import traceback
from collections.abc import Callable
from itertools import count
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot


class _Signals(QObject):
    succeeded = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)
    finished = pyqtSignal(int)


class _Task(QRunnable):
    def __init__(self, token: int, fn: Callable[[], Any]) -> None:
        super().__init__(); self.token, self.fn, self.signals = token, fn, _Signals()

    @pyqtSlot()
    def run(self) -> None:
        try: self.signals.succeeded.emit(self.token, self.fn())
        except Exception: self.signals.failed.emit(self.token, traceback.format_exc())
        finally: self.signals.finished.emit(self.token)


class TaskRunner(QObject):
    """Runs service calls off the GUI thread and dispatches results on it."""

    busy_changed = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None, *, threads: int = 4) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(threads)
        self._ids = count(1); self._tasks: dict[int, tuple[_Task, object, object, object, str | None]] = {}
        self._channels: dict[str, int] = {}

    def submit(self, fn, *, on_result=None, on_error=None, on_finished=None, channel: str | None = None) -> int:
        token = next(self._ids); task = _Task(token, fn)
        self._tasks[token] = (task, on_result, on_error, on_finished, channel)
        if channel: self._channels[channel] = token
        task.signals.succeeded.connect(self._succeeded)
        task.signals.failed.connect(self._failed)
        task.signals.finished.connect(self._finished)
        if len(self._tasks) == 1: self.busy_changed.emit(True)
        self._pool.start(task); return token

    def _current(self, token: int) -> bool:
        item = self._tasks.get(token)
        return bool(item and (item[4] is None or self._channels.get(item[4]) == token))

    @pyqtSlot(int, object)
    def _succeeded(self, token: int, value: object) -> None:
        item = self._tasks.get(token)
        if item and self._current(token) and item[1]: item[1](value)

    @pyqtSlot(int, str)
    def _failed(self, token: int, trace: str) -> None:
        item = self._tasks.get(token)
        if item and self._current(token) and item[2]: item[2](trace)

    @pyqtSlot(int)
    def _finished(self, token: int) -> None:
        item = self._tasks.pop(token, None)
        if item and self._current_or_unchanneled(token, item) and item[3]: item[3]()
        if item and item[4] and self._channels.get(item[4]) == token: self._channels.pop(item[4], None)
        if not self._tasks: self.busy_changed.emit(False)

    def _current_or_unchanneled(self, token: int, item: tuple) -> bool:
        return item[4] is None or self._channels.get(item[4]) == token
