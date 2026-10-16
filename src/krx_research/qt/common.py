from __future__ import annotations

import traceback
from typing import Any, Callable

import pandas as pd
from krx_research.qt.presentation.column_catalog import label_for
from krx_research.qt.presentation.table_policy import DEFAULT_TABLE_POLICY, TablePresentationPolicy
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRunnable, Qt, QThreadPool, Signal, Slot


class DataFrameModel(QAbstractTableModel):
    """Reusable Qt table model with one presentation policy for all programs."""

    def __init__(
        self,
        frame: pd.DataFrame | None = None,
        parent: QObject | None = None,
        *,
        header_labels: dict[str, str] | None = None,
        policy: TablePresentationPolicy | None = None,
    ):
        super().__init__(parent)
        self._policy = policy or DEFAULT_TABLE_POLICY
        self._frame = self._policy.prepare(frame)
        self._header_labels = dict(header_labels or {})

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def set_frame(self, frame: pd.DataFrame | None, *, header_labels: dict[str, str] | None = None) -> None:
        self.beginResetModel()
        self._frame = self._policy.prepare(frame)
        if header_labels is not None:
            self._header_labels = dict(header_labels)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._frame)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._frame.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        column = str(self._frame.columns[index.column()])
        value = self._frame.iat[index.row(), index.column()]
        if role == Qt.DisplayRole:
            return self._policy.format_value(column, value)
        if role == Qt.TextAlignmentRole:
            return self._policy.alignment(column, value)
        if role == Qt.UserRole:
            return self._frame.iloc[index.row()].to_dict()
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            column = str(self._frame.columns[section])
            if role == Qt.DisplayRole:
                return self._header_labels.get(column, label_for(column))
            if role == Qt.TextAlignmentRole:
                return self._policy.header_alignment(column, self._frame.iloc[:, section])
            return None
        if role == Qt.DisplayRole:
            return str(section + 1)
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        if self._frame.empty or not 0 <= column < len(self._frame.columns):
            return
        name = self._frame.columns[column]
        values = self._frame[name]
        numeric = pd.to_numeric(values, errors="coerce")
        key = numeric if numeric.notna().sum() == values.notna().sum() else values.astype(str).str.casefold()
        self.layoutAboutToBeChanged.emit()
        self._frame = (self._frame.assign(_sort_key=key)
                       .sort_values("_sort_key", ascending=order == Qt.AscendingOrder,
                                    kind="mergesort", na_position="last")
                       .drop(columns="_sort_key").reset_index(drop=True))
        self.layoutChanged.emit()


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self.fn(*self.args, **self.kwargs))
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()


def run_worker(
    owner: QObject,
    fn: Callable[..., Any],
    *,
    on_result: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_finished: Callable[[], None] | None = None,
) -> FunctionWorker:
    worker = FunctionWorker(fn)
    if on_result is not None:
        worker.signals.result.connect(on_result)
    if on_error is not None:
        worker.signals.error.connect(on_error)
    if on_finished is not None:
        worker.signals.finished.connect(on_finished)
    pool = QThreadPool.globalInstance()
    pool.start(worker)
    workers = getattr(owner, "_qt_workers", None)
    if workers is None:
        workers = []
        setattr(owner, "_qt_workers", workers)
    workers.append(worker)
    worker.signals.finished.connect(lambda w=worker: workers.remove(w) if w in workers else None)
    return worker
