from __future__ import annotations

from pathlib import Path
import re
from typing import Callable

import pandas as pd
from PySide6.QtCore import QDate, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from krx_research.database import resolve_database_target
from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.presentation.column_catalog import label_for
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.box_breakout import BoxBreakoutQuery, BoxBreakoutSearchService
from krx_research.qt.services.pattern_similarity import (
    MovingAverageKind, MovingAverageSpec, PatternSearchQuery, PatternSimilaritySearchService,
    PatternVectorCache, PostgreSQLPatternRepository,
)
from krx_research.ui.data import WorkstationData


class SearchWorker(QObject):
    succeeded = Signal(list)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, search: Callable[[], list[dict]]):
        super().__init__(); self._search = search

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._search())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class PatternSearchDialog(QDialog):
    """Local-only GUI for deterministic similarity and box-breakout searches."""

    def __init__(self, root: Path, parent=None, *, repository=None, chart_service=None):
        super().__init__(parent)
        self._root, self._thread, self._worker = Path(root), None, None
        self._rows, self._charts = [], []
        target = resolve_database_target(self._root, read_only=True) if repository is None or chart_service is None else None
        self._repository = repository or PostgreSQLPatternRepository(target)
        self._chart_service = chart_service or ChartService(WorkstationData(target))
        self.setWindowTitle("메뉴 3 · 주가 패턴 검색")
        self.resize(1100, 720)
        self._build(); self._mode_changed(0)

    def _build(self) -> None:
        self.mode = QComboBox(); self.mode.addItems(("이동평균 유사 패턴", "박스권 돌파"))
        self.security = QLineEdit(); self.security.setPlaceholderText("종목코드 또는 정확한 종목명")
        today = QDate.currentDate()
        self.start = QDateEdit(today.addMonths(-4), calendarPopup=True)
        self.end = QDateEdit(today, calendarPopup=True)
        self.start.setMaximumDate(today); self.end.setMaximumDate(today)
        self.average = QComboBox(); self.average.addItems(tuple(kind.value for kind in MovingAverageKind))
        self.periods = QLineEdit("5, 20, 60")
        self.volume = QCheckBox("거래량 패턴 포함")
        self.top = QSpinBox(); self.top.setRange(1, 100); self.top.setValue(20)
        form = QFormLayout()
        for label, widget in (("검색 종류", self.mode), ("기준 종목", self.security),
                              ("시작일", self.start), ("종료일", self.end),
                              ("이동평균 종류", self.average), ("이동평균 기간", self.periods),
                              ("", self.volume), ("유사 결과 수", self.top)):
            form.addRow(label, widget)
        self.help = QLabel(); self.help.setWordWrap(True)
        self.table = QTableWidget(); self.table.setAlternatingRowColors(True)
        self.status = QLabel("조건을 입력한 뒤 검색하십시오.")
        self.search_button = QPushButton("검색")
        self.chart_button = QPushButton("선택 종목 차트"); self.chart_button.setEnabled(False)
        self.close_button = QPushButton("닫기")
        buttons = QHBoxLayout(); buttons.addWidget(self.search_button); buttons.addWidget(self.chart_button)
        buttons.addStretch(1); buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addWidget(self.help)
        layout.addWidget(self.status); layout.addWidget(self.table, 1); layout.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.search_button.clicked.connect(self._search); self.close_button.clicked.connect(self.close)
        self.chart_button.clicked.connect(self._open_chart); self.table.cellDoubleClicked.connect(self._open_chart)

    def _mode_changed(self, index: int) -> None:
        similar = index == 0
        for widget in (self.average, self.periods, self.volume): widget.setEnabled(similar)
        self.help.setText(
            "선택한 종목의 주가와 이동평균선 모양을 같은 기간의 전체 종목과 비교합니다. "
            "이동평균은 SMA·EMA·WMA 및 원하는 기간을 지정할 수 있습니다."
            if similar else
            "기준 종목과 기간에서 박스 상단·하단, 돌파 시점, 돌파율과 거래량 변화를 자동으로 파악한 뒤 "
            "같은 기간의 전체 종목에서 유사한 박스권 돌파 패턴을 찾습니다."
        )

    def _search(self) -> None:
        try:
            search = self._command()
        except Exception as exc:
            QMessageBox.warning(self, "입력 확인", str(exc)); return
        worker, thread = SearchWorker(search), QThread(self)
        worker.moveToThread(thread); thread.started.connect(worker.run)
        worker.succeeded.connect(self._show_rows); worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater); thread.finished.connect(self._finished)
        self._worker, self._thread = worker, thread
        self.search_button.setEnabled(False); self.close_button.setEnabled(False)
        self.status.setText("로컬 DB에서 검색 중..."); thread.start()

    def _command(self) -> Callable[[], list[dict]]:
        start, end = self.start.date().toPython(), self.end.date().toPython()
        if self.mode.currentIndex() == 1:
            query = BoxBreakoutQuery(self.security.text().strip(), start, end, self.top.value())
            return lambda: BoxBreakoutSearchService(self._repository).search(query)
        periods = tuple(map(int, filter(None, re.split(r"[ ,]+", self.periods.text().strip()))))
        query = PatternSearchQuery(
            self.security.text().strip(), start, end,
            MovingAverageSpec(MovingAverageKind(self.average.currentText()), periods),
            self.top.value(), True, self.volume.isChecked(),
        )
        cache = PatternVectorCache(self._root / ".local_cache" / "pattern_vectors")
        return lambda: PatternSimilaritySearchService(self._repository, cache).search(query)

    @Slot(list)
    def _show_rows(self, rows: list[dict]) -> None:
        self._rows = rows
        columns = list(rows[0]) if rows else []
        self.table.setRowCount(len(rows)); self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([label_for(column) for column in columns])
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = row.get(column)
                self.table.setItem(row_index, column_index, QTableWidgetItem("" if value is None else str(value)))
        self.chart_button.setEnabled(bool(rows))
        self.table.resizeColumnsToContents(); self.status.setText(f"검색 완료: {len(rows)}종목")

    def _open_chart(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            QMessageBox.information(self, "차트", "결과 종목을 선택하십시오."); return
        ticker = str(self._rows[row]["stock_code"])
        frame = pd.DataFrame(self._rows)
        chart = ChartWindow(
            self._chart_service, ticker, parent=self, navigation_enabled=True,
            navigation_frame=frame, navigation_labels={column: label_for(column) for column in frame.columns},
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda _=None, item=chart: self._charts.remove(item) if item in self._charts else None)
        chart.show()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.status.setText("검색 실패"); QMessageBox.critical(self, "검색 오류", message)

    def _finished(self) -> None:
        self._thread = self._worker = None
        self.search_button.setEnabled(True); self.close_button.setEnabled(True)

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.status.setText("검색이 끝난 뒤 창을 닫을 수 있습니다."); event.ignore(); return
        super().closeEvent(event)
