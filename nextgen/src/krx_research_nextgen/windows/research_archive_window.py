from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDateEdit, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from krx_research.database.settings import resolve_database_target
from krx_research.research_archive import ResearchArchiveService
from krx_research.qt.services.error_log_service import ErrorLogService
from krx_research_nextgen.workers.task_runner import TaskRunner


class ResearchArchiveWindow(QMainWindow):
    """PyQt6 view over the shared immutable research archive service."""

    stock_requested = pyqtSignal(str)
    _RIGHT = {"source_order", "source_return_pct", "db_return_pct", "source_trading_value_eok",
              "db_trading_value_eok", "db_close"}
    _CENTER = {"report_date", "document_kind", "document_ticker", "ticker", "authority"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = ResearchArchiveService(resolve_database_target(Path(r"C:\stock")))
        self._tasks = TaskRunner(self)
        self._logs = ErrorLogService(Path(r"C:\stock\logs"), "research_archive_error.log")
        self._operation = "initialize"
        self.setWindowTitle("리포트·이미지 연구자료 · 원본 보존 · Stock DB 값 우선")
        self.resize(1600, 900)
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        controls = QHBoxLayout(); layout.addLayout(controls)
        import_button = QPushButton("PDF·이미지 원본 등록"); import_button.clicked.connect(self._choose); controls.addWidget(import_button)
        controls.addWidget(QLabel("시작일")); self.start = QDateEdit(calendarPopup=True); controls.addWidget(self.start)
        controls.addWidget(QLabel("종료일")); self.end = QDateEdit(calendarPopup=True); controls.addWidget(self.end)
        self.search = QLineEdit(); self.search.setPlaceholderText("종목명·코드·제목·사유"); controls.addWidget(self.search, 1)
        query = QPushButton("기간 조회"); query.clicked.connect(self._query); controls.addWidget(query)
        self.table = QTableWidget(); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self._chart); layout.addWidget(self.table, 1)
        self.status = QLabel("원본값과 Stock DB 확정값을 분리하여 보관합니다."); layout.addWidget(self.status)
        today = date.today(); first = today - timedelta(days=365)
        self.start.setDate(QDate(first.year, first.month, first.day)); self.end.setDate(QDate.currentDate())
        self._tasks.submit(self._service.initialize, on_error=self._error, channel="init")

    def _choose(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "연구자료 원본 선택", "", "연구자료 (*.pdf *.png *.jpg *.jpeg *.webp)")
        if not files: return
        if any(not path.lower().endswith(".pdf") for path in files) and QMessageBox.question(
            self, "Codex 이미지 분석 확인",
            "선택한 이미지가 종목·수치 전사를 위해 Codex로 전송되며 ChatGPT 요금제 사용량을 사용합니다.\n"
            "PDF는 전송하지 않습니다. 계속하시겠습니까?",
        ) != QMessageBox.StandardButton.Yes: return
        self.status.setText("원본을 검증·보관하는 중입니다...")
        self._operation = "import"
        self._tasks.submit(lambda: self._service.import_files(files), on_result=self._imported,
                           on_error=self._error, channel="import")

    def _imported(self, results) -> None:
        QMessageBox.information(self, "등록 완료", f"{len(results):,}개 원본을 보관했습니다.")
        self._query()

    def _query(self) -> None:
        start, end, search = self.start.date().toPyDate(), self.end.date().toPyDate(), self.search.text()
        self.status.setText("연구자료를 조회하는 중입니다...")
        self._operation = "query"
        self._tasks.submit(lambda: self._service.query(start, end, search), on_result=self._show,
                           on_error=self._error, channel="query")

    def _show(self, frame: pd.DataFrame) -> None:
        self.table.clear(); self.table.setRowCount(len(frame)); self.table.setColumnCount(len(frame.columns))
        self.table.setHorizontalHeaderLabels([str(column) for column in frame.columns])
        for column in range(self.table.columnCount()):
            self.table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for row, values in enumerate(frame.itertuples(index=False, name=None)):
            for column, value in enumerate(values):
                name = str(frame.columns[column]); item = QTableWidgetItem("" if pd.isna(value) else str(value))
                alignment = (Qt.AlignmentFlag.AlignRight if name in self._RIGHT else
                             Qt.AlignmentFlag.AlignCenter if name in self._CENTER else Qt.AlignmentFlag.AlignLeft)
                item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter); self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents(); self.status.setText(f"연구자료 {len(frame):,}건 · Stock DB 값 우선")

    def _chart(self) -> None:
        columns = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
        if "ticker" not in columns or self.table.currentRow() < 0: return
        item = self.table.item(self.table.currentRow(), columns.index("ticker"))
        if item and item.text(): self.stock_requested.emit(item.text())

    def _error(self, trace: str) -> None:
        path = self._logs.write(str(trace))
        lines = [line.strip() for line in str(trace).splitlines() if line.strip()]
        exception = next((line.split(":", 1)[1].strip() for line in reversed(lines)
                          if line.startswith(("RuntimeError:", "ValueError:"))), "알 수 없는 오류")
        prefix = "등록 실패 · 원본은 보관되지 않았습니다.\n" if self._operation == "import" else ""
        log = f"\n\n기술 로그: {path}" if path else ""
        message = prefix + exception + log
        self.status.setText(prefix.replace("\n", " ") + exception)
        QMessageBox.critical(self, "연구자료 오류", message)
