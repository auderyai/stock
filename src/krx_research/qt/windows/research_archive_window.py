from __future__ import annotations

from datetime import date

import pandas as pd
from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QVBoxLayout, QWidget, QMessageBox,
)

from krx_research.qt.widgets.result_table import ResultTable


class ResearchArchiveView(QMainWindow):
    queryRequested = Signal(object, object, str)
    importRequested = Signal(list)
    chartRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KRX 연구자료 보관 · PDF·이미지 · DB 값 우선")
        self.resize(1600, 900)
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        controls = QHBoxLayout(); layout.addLayout(controls)
        button = QPushButton("PDF·이미지 원본 등록"); button.clicked.connect(self._choose); controls.addWidget(button)
        controls.addWidget(QLabel("시작일")); self.start = QDateEdit(calendarPopup=True); controls.addWidget(self.start)
        controls.addWidget(QLabel("종료일")); self.end = QDateEdit(calendarPopup=True); controls.addWidget(self.end)
        self.search = QLineEdit(); self.search.setPlaceholderText("종목명·코드·제목·사유"); controls.addWidget(self.search, 1)
        query = QPushButton("기간 조회"); query.clicked.connect(self._query); controls.addWidget(query)
        self.table = ResultTable(); self.table.chartRequested.connect(self._chart); layout.addWidget(self.table, 1)
        self.status = QLabel("원본은 보존하고 이미지/PDF 값과 Stock DB 확정값을 분리합니다."); layout.addWidget(self.status)

    def set_period(self, start: date, end: date) -> None:
        self.start.setDate(QDate(start.year, start.month, start.day))
        self.end.setDate(QDate(end.year, end.month, end.day))

    def _query(self) -> None:
        self.queryRequested.emit(self.start.date().toPython(), self.end.date().toPython(), self.search.text())

    def _choose(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "연구자료 원본 선택", "", "연구자료 (*.pdf *.png *.jpg *.jpeg *.webp)"
        )
        images = [path for path in files if not path.lower().endswith(".pdf")]
        if images and QMessageBox.question(
            self, "이미지 분석 전송 확인",
            "선택한 이미지가 종목·수치 전사를 위해 OpenAI API로 전송됩니다. 계속하시겠습니까?",
        ) != QMessageBox.Yes:
            return
        if files:
            self.importRequested.emit(files)

    def set_frame(self, frame: pd.DataFrame, status: str) -> None:
        self.table.set_frame(frame)
        self.status.setText(status)

    def _chart(self) -> None:
        ticker = self.table.current_ticker()
        if ticker:
            self.chartRequested.emit(ticker)
