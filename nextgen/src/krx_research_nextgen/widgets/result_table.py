"""Common PyQt6 result table backed by the shared presentation policy."""

from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from krx_research.presentation.table_policy import (
    DEFAULT_TABLE_POLICY,
    TablePresentationPolicy,
)
from krx_research.qt.presentation.column_catalog import label_for


_ALIGNMENTS = {
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
}


class DataFrameModel(QAbstractTableModel):
    """Typed sortable frame model; numeric text never sorts lexicographically."""

    def __init__(
        self,
        frame: pd.DataFrame | None = None,
        parent=None,
        *,
        labels: dict[str, str] | None = None,
        alignment_overrides: dict[str, str] | None = None,
        policy: TablePresentationPolicy | None = None,
    ) -> None:
        super().__init__(parent)
        self._policy = policy or DEFAULT_TABLE_POLICY
        self._frame = self._policy.prepare(frame)
        self._labels = dict(labels or {})
        self._alignment_overrides = dict(alignment_overrides or {})

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def formatted(self, column: str, value) -> str:
        return self._policy.format_value(column, value)

    def alignment(self, column: str, value) -> str:
        return self._alignment_overrides.get(column, self._policy.alignment(column, value))

    def set_frame(
        self,
        frame: pd.DataFrame | None,
        *,
        labels: dict[str, str] | None = None,
        alignment_overrides: dict[str, str] | None = None,
    ) -> None:
        self.beginResetModel()
        self._frame = self._policy.prepare(frame)
        if labels is not None:
            self._labels = dict(labels)
        self._alignment_overrides = dict(alignment_overrides or {})
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._frame)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._frame.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        column = str(self._frame.columns[index.column()])
        value = self._frame.iat[index.row(), index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._policy.format_value(column, value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGNMENTS[self.alignment(column, value)]
        if role == Qt.ItemDataRole.UserRole:
            return self._frame.iloc[index.row()].to_dict()
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if orientation == Qt.Orientation.Horizontal:
            column = str(self._frame.columns[section])
            if role == Qt.ItemDataRole.DisplayRole:
                return self._labels.get(column, label_for(column))
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return _ALIGNMENTS[self._policy.header_alignment(column)]
            return None
        return str(section + 1) if role == Qt.ItemDataRole.DisplayRole else None

    def sort(
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        if self._frame.empty or not 0 <= column < len(self._frame.columns):
            return
        name = str(self._frame.columns[column])
        key = self._policy.sort_key(self._frame[name])
        ticker = next(
            (item for item in self._policy.ticker_columns if item in self._frame.columns),
            None,
        )
        prepared = self._frame.assign(_sort_key=key)
        columns = ["_sort_key"] + ([ticker] if ticker and ticker != name else [])
        ascending = [order == Qt.SortOrder.AscendingOrder] + [True] * (len(columns) - 1)
        self.layoutAboutToBeChanged.emit()
        self._frame = (
            prepared.sort_values(columns, ascending=ascending, kind="mergesort", na_position="last")
            .drop(columns="_sort_key")
            .reset_index(drop=True)
        )
        self.layoutChanged.emit()

    def apply_default_sort(self) -> tuple[int, Qt.SortOrder] | None:
        default = self._policy.default_sort(self._frame)
        if default is None:
            return None
        name, ascending = default
        column = self._frame.columns.get_loc(name)
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        self.sort(column, order)
        return column, order


class ResultTable(QTableView):
    """One PyQt6 result-grid behavior for sorting, identity and chart requests."""

    chartRequested = pyqtSignal()
    currentTickerChanged = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        *,
        policy: TablePresentationPolicy | None = None,
        identity_columns: tuple[str, ...] = ("ticker", "stock_code", "code"),
        identity_width: int = 6,
    ) -> None:
        super().__init__(parent)
        self._identity_columns = identity_columns
        self._identity_width = identity_width
        self._model = DataFrameModel(pd.DataFrame(), self, policy=policy)
        self.setModel(self._model)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(True)
        self.doubleClicked.connect(lambda _index: self.chartRequested.emit())
        self.selectionModel().currentRowChanged.connect(self._emit_ticker)

    @property
    def frame(self) -> pd.DataFrame:
        return self._model.frame

    def set_frame(
        self,
        frame: pd.DataFrame | None,
        *,
        labels: dict[str, str] | None = None,
        alignment_overrides: dict[str, str] | None = None,
    ) -> None:
        self._model.set_frame(
            frame, labels=labels, alignment_overrides=alignment_overrides
        )
        default = self._model.apply_default_sort()
        if default is not None:
            self.horizontalHeader().setSortIndicator(*default)
        self.resizeColumnsToContents()
        if not self.frame.empty:
            self.selectRow(0)

    def current_ticker(self) -> str | None:
        index = self.currentIndex()
        if not index.isValid() or self.frame.empty:
            return None
        row = self.frame.iloc[index.row()]
        for column in self._identity_columns:
            value = row.get(column)
            if value is None or str(value).strip().lower() in {"", "nan"}:
                continue
            text = str(value).strip().removesuffix(".0")
            return text.zfill(self._identity_width) if self._identity_width and text.isdigit() else text
        return None

    def current_record(self) -> dict:
        index = self.currentIndex()
        return self.frame.iloc[index.row()].to_dict() if index.isValid() else {}

    def navigation_payload(self, title: str) -> dict | None:
        """Return the currently sorted visible rows for synchronized chart navigation."""

        if self.frame.empty:
            return None
        ticker_column = next(
            (column for column in self._identity_columns if column in self.frame.columns),
            None,
        )
        if ticker_column is None:
            return None
        columns = list(self.frame.columns)
        headers = tuple(
            str(self._model.headerData(index, Qt.Orientation.Horizontal))
            for index in range(len(columns))
        )
        alignments = tuple(
            self._model.alignment(column, self.frame[column].dropna().iloc[0])
            if self.frame[column].notna().any()
            else "left"
            for column in columns
        )
        items = []
        for _, row in self.frame.iterrows():
            code = str(row[ticker_column]).strip().removesuffix(".0")
            if self._identity_width and code.isdigit():
                code = code.zfill(self._identity_width)
            values = tuple(
                self._model.formatted(column, row[column])
                for column in columns
            )
            items.append({"code": code, "values": values})
        return {
            "title": title,
            "headers": headers,
            "items": items,
            "alignments": alignments,
        }

    def _emit_ticker(self, *_args) -> None:
        ticker = self.current_ticker()
        if ticker:
            self.currentTickerChanged.emit(ticker)
