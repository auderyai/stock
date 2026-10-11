from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QItemSelectionModel, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from krx_research.qt.common import DataFrameModel
from krx_research.qt.presentation.table_policy import TablePresentationPolicy


class ResultTable(QTableView):
    """Common PySide6 result grid used by workstation and synchronized charts."""

    chartRequested = Signal()
    currentTickerChanged = Signal(str)

    def __init__(self, parent=None, *, policy: TablePresentationPolicy | None = None, identity_columns: tuple[str, ...] = ("ticker", "stock_code", "code"), identity_width: int = 6):
        super().__init__(parent)
        self._identity_columns = identity_columns
        self._identity_width = identity_width
        self._model = DataFrameModel(pd.DataFrame(), self, policy=policy)
        self.setModel(self._model)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsMovable(True)
        self.doubleClicked.connect(lambda _idx: self.chartRequested.emit())
        self.selectionModel().currentRowChanged.connect(self._emit_ticker)

    @property
    def frame(self) -> pd.DataFrame:
        return self._model.frame

    def set_frame(self, frame: pd.DataFrame, *, header_labels: dict[str, str] | None = None) -> None:
        self.setSortingEnabled(False)
        self._model.set_frame(frame, header_labels=header_labels)
        self.setSortingEnabled(True)
        self.resizeColumnsToContents()

    def current_ticker(self) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid() or self.frame.empty:
            return None
        row = self.frame.iloc[idx.row()]
        for name in self._identity_columns:
            value = row.get(name)
            if value is not None and str(value).strip() and str(value).lower() != "nan":
                text = str(value).strip().replace(".0", "")
                return text.zfill(self._identity_width) if self._identity_width else text
        return None

    def select_ticker(self, ticker: str) -> bool:
        target = str(ticker).strip().replace(".0", "")
        if self._identity_width:
            target = target.zfill(self._identity_width)
        if self.frame.empty:
            return False
        ticker_column = next((c for c in self._identity_columns if c in self.frame.columns), None)
        if not ticker_column:
            return False
        values = self.frame[ticker_column].astype(str).str.replace(r"\.0$", "", regex=True)
        if self._identity_width:
            values = values.str.zfill(self._identity_width)
        matches = values.index[values == target]
        if len(matches) == 0:
            return False
        row_pos = self.frame.index.get_loc(matches[0])
        index = self._model.index(int(row_pos), 0)
        self.setCurrentIndex(index)
        self.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.scrollTo(index)
        return True

    def _emit_ticker(self, *_args):
        ticker = self.current_ticker()
        if ticker:
            self.currentTickerChanged.emit(ticker)
