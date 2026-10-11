from __future__ import annotations
from datetime import date
import pandas as pd
from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import QDateEdit, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget
from krx_research.qt.widgets.result_table import ResultTable
from krx_research.qt.presentation.column_catalog import label_for
from krx_research.qt.windows.daily_image_preview import DailyImagePreviewDialog


class FeaturedResearchView(QMainWindow):
    queryRequested = Signal(object, object)
    repeatedRequested = Signal(object, object)
    refreshRequested = Signal(object, object)
    importRequested = Signal(list)
    chartRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(1500, 850)
        self.setWindowTitle("KRX 일일 특징주 · PySide6")
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        controls = QHBoxLayout(); layout.addLayout(controls)
        import_button = QPushButton("PNG·JPG 선택·등록"); import_button.clicked.connect(self._choose_files); controls.addWidget(import_button)
        controls.addWidget(QLabel("입력일")); self.input_date = QDateEdit(QDate.currentDate(), calendarPopup=True); controls.addWidget(self.input_date)
        controls.addWidget(QLabel("시작일")); self.start = QDateEdit(calendarPopup=True); controls.addWidget(self.start)
        controls.addWidget(QLabel("종료일")); self.end = QDateEdit(calendarPopup=True); controls.addWidget(self.end)
        query_button = QPushButton("기간 조회"); query_button.clicked.connect(self._query); controls.addWidget(query_button)
        repeated_button = QPushButton("기간 중복 종목"); repeated_button.clicked.connect(self._repeated); controls.addWidget(repeated_button)
        refresh_button = QPushButton("누락 항목 다시 찾기"); refresh_button.clicked.connect(self._refresh); controls.addWidget(refresh_button); controls.addStretch(1)
        self.table = ResultTable(); self.model = self.table._model; self.table.chartRequested.connect(self._chart); layout.addWidget(self.table, 1)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(120); layout.addWidget(self.detail)
        self.status = QLabel(""); layout.addWidget(self.status)
        self.table.selectionModel().currentRowChanged.connect(self._details)

    def set_date(self, value: date) -> None:
        q = QDate(value.year, value.month, value.day); self.start.setDate(q); self.end.setDate(q)

    def period(self): return self.start.date().toPython(), self.end.date().toPython()
    def registration_date(self): return self.input_date.date().toPython()
    def _query(self): a,b=self.period(); self.queryRequested.emit(a,b)
    def _repeated(self): a,b=self.period(); self.repeatedRequested.emit(a,b)
    def _refresh(self): a,b=self.period(); self.refreshRequested.emit(a,b)
    def _choose_files(self):
        files,_=QFileDialog.getOpenFileNames(self,"일일 특징주 이미지 선택","","이미지 (*.png *.jpg *.jpeg *.webp)")
        if files: self.importRequested.emit(files)
    def confirm_images(self,plan): return DailyImagePreviewDialog(plan.rows,self).exec()
    def set_frame(self, frame: pd.DataFrame, status: str) -> None:
        self.table.set_frame(frame); self.status.setText(status)
    def _row(self):
        idx=self.table.currentIndex(); return None if not idx.isValid() or self.model.frame.empty else self.model.frame.iloc[idx.row()]
    def _details(self,*_):
        row=self._row(); self.detail.setPlainText("" if row is None else "\n".join(f"{label_for(str(k))}: {v}" for k,v in row.items()))
    def _chart(self):
        row=self._row()
        if row is not None:
            ticker=row.get("ticker") or row.get("stock_code")
            if ticker: self.chartRequested.emit(str(ticker).zfill(6))
