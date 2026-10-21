from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtWidgets import (
    QDateEdit, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from krx_research_nextgen.controllers.research_archive_controller import ResearchArchiveController
from krx_research_nextgen.widgets.result_table import ResultTable


class ResearchArchiveWindow(QMainWindow):
    """PyQt6 view over the shared immutable research archive service."""

    stock_requested = pyqtSignal(str)
    def __init__(self, controller: ResearchArchiveController, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("리포트·이미지 연구자료 · 원본 보존 · Stock DB 값 우선")
        self.resize(1600, 900)
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        controls = QHBoxLayout(); layout.addLayout(controls)
        import_button = QPushButton("PDF·이미지 원본 등록"); import_button.clicked.connect(self._choose); controls.addWidget(import_button)
        controls.addWidget(QLabel("시작일")); self.start = QDateEdit(calendarPopup=True); controls.addWidget(self.start)
        controls.addWidget(QLabel("종료일")); self.end = QDateEdit(calendarPopup=True); controls.addWidget(self.end)
        self.search = QLineEdit(); self.search.setPlaceholderText("종목명·코드·제목·사유"); controls.addWidget(self.search, 1)
        query = QPushButton("기간 조회"); query.clicked.connect(self._query); controls.addWidget(query)
        self.table = ResultTable(); self.table.chartRequested.connect(self._chart); layout.addWidget(self.table, 1)
        self.status = QLabel("원본값과 Stock DB 확정값을 분리하여 보관합니다."); layout.addWidget(self.status)
        today = date.today(); first = today - timedelta(days=365)
        self.start.setDate(QDate(first.year, first.month, first.day)); self.end.setDate(QDate.currentDate())
        controller.imported.connect(self._imported)
        controller.queried.connect(self._show)
        controller.failed.connect(self._error)
        controller.initialize()

    def _choose(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "연구자료 원본 선택", "", "연구자료 (*.pdf *.png *.jpg *.jpeg *.webp)")
        if not files: return
        if any(not path.lower().endswith(".pdf") for path in files) and QMessageBox.question(
            self, "Codex 이미지 분석 확인",
            "선택한 이미지가 종목·수치 전사를 위해 Codex로 전송되며 ChatGPT 요금제 사용량을 사용합니다.\n"
            "PDF는 전송하지 않습니다. 계속하시겠습니까?",
        ) != QMessageBox.StandardButton.Yes: return
        self.status.setText("원본을 검증·보관하는 중입니다...")
        self._controller.import_files(files)

    def _imported(self, results) -> None:
        QMessageBox.information(self, "등록 완료", f"{len(results):,}개 원본을 보관했습니다.")
        self._query()

    def _query(self) -> None:
        start, end, search = self.start.date().toPyDate(), self.end.date().toPyDate(), self.search.text()
        self.status.setText("연구자료를 조회하는 중입니다...")
        self._controller.query(start, end, search)

    def _show(self, frame: pd.DataFrame) -> None:
        self.table.set_frame(frame)
        self.status.setText(f"연구자료 {len(frame):,}건 · Stock DB 값 우선")

    def _chart(self) -> None:
        ticker = self.table.current_ticker()
        if ticker: self.stock_requested.emit(ticker)

    def _error(self, operation: str, exception: str, path: str) -> None:
        prefix = "등록 실패 · 원본은 보관되지 않았습니다.\n" if operation == "import" else ""
        log = f"\n\n기술 로그: {path}" if path else ""
        message = prefix + exception + log
        self.status.setText(prefix.replace("\n", " ") + exception)
        QMessageBox.critical(self, "연구자료 오류", message)
