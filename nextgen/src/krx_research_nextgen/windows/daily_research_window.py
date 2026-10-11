from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from numbers import Number

import pandas as pd
from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from krx_research.qt.presentation.column_catalog import label_for
from krx_research.qt.services.featured_service import FeaturedResearchService
from krx_research.qt.services.theme_service import ThemeResearchService
from krx_research_nextgen.presentation.number_format import format_number
from krx_research_nextgen.workers.task_runner import TaskRunner


@dataclass(frozen=True)
class DailyResearchSpec:
    title: str
    kind: str


SPECS = {
    "featured": DailyResearchSpec("일일 특징주", "featured"),
    "theme": DailyResearchSpec("일일 테마", "theme"),
}

VISIBLE_COLUMNS = {
    "featured": ("report_date", "ticker", "stock_name", "return_pct", "trading_value_eok",
                 "market", "theme_name", "reason", "db_trade_date"),
    "theme": ("report_date", "theme_name", "ticker", "stock_name", "return_pct",
              "trading_value_eok", "market", "reason", "db_trade_date"),
    "repeated": ("appearance_count", "ticker", "stock_name", "market", "report_dates",
                 "themes", "average_return_pct", "maximum_return_pct", "latest_report_date",
                 "trading_value_eok"),
}

PREVIEW_COLUMNS = (
    ("report_date", "기준일"), ("category", "테마·분류"), ("ticker", "종목코드"),
    ("stock_name", "종목명"), ("source_return_pct", "이미지 등락률(%)"),
    ("db_return_pct", "DB 등락률(%)"), ("final_return_pct", "확정 등락률(%)"),
    ("source_trading_value_eok", "이미지 거래대금(억원)"),
    ("db_trading_value_eok", "DB 거래대금(억원)"),
    ("final_trading_value_eok", "확정 거래대금(억원)"), ("reason", "사유(이미지 원문)"),
    ("authority", "확정 상태"),
)


class DailyImagePreviewDialog(QDialog):
    """Read-only source/DB comparison required before operational registration."""

    def __init__(self, rows: tuple[dict, ...], parent=None) -> None:
        super().__init__(parent); self.setWindowTitle("이미지 분석·Stock DB 비교 확인"); self.resize(1350, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Stock DB 값이 있는 항목은 DB 값으로 확정합니다. 확정 등록하면 같은 기준일의 기존 자료를 대체합니다."))
        table = QTableWidget(len(rows), len(PREVIEW_COLUMNS)); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setHorizontalHeaderLabels([label for _, label in PREVIEW_COLUMNS])
        for column in range(len(PREVIEW_COLUMNS)): table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for row_index, row in enumerate(rows):
            for column_index, (key, _) in enumerate(PREVIEW_COLUMNS):
                value = row.get(key); item = QTableWidgetItem(DailyResearchWindow._text(value, key))
                item.setTextAlignment(DailyResearchWindow._alignment(key, value)); table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents(); table.setColumnWidth(10, 480); layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("확정 등록")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class DailyResearchWindow(QMainWindow):
    """PyQt6 view for the shared, Qt-free daily research services."""

    chart_requested = pyqtSignal(str)

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.spec = SPECS[kind]
        self.service = FeaturedResearchService() if kind == "featured" else ThemeResearchService()
        self.tasks = TaskRunner(self)
        self.tasks.busy_changed.connect(self._busy)
        self.frame = pd.DataFrame()
        self.setWindowTitle(f"KRX {self.spec.title} · PyQt6 · PostgreSQL")
        self.resize(1500, 850)
        self._build()
        self._initialize()

    def _build(self) -> None:
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        controls = QHBoxLayout(); layout.addLayout(controls)
        self.import_button = QPushButton("PNG·JPG 선택·등록")
        controls.addWidget(self.import_button); controls.addWidget(QLabel("입력일"))
        self.input_date = QDateEdit(QDate.currentDate(), calendarPopup=True); controls.addWidget(self.input_date)
        controls.addWidget(QLabel("시작일"))
        self.start = QDateEdit(calendarPopup=True); controls.addWidget(self.start)
        controls.addWidget(QLabel("종료일")); self.end = QDateEdit(calendarPopup=True); controls.addWidget(self.end)
        self.query_button = QPushButton("기간 조회"); controls.addWidget(self.query_button)
        self.repeated_button = QPushButton("기간 중복 종목")
        if self.spec.kind == "featured": controls.addWidget(self.repeated_button)
        self.refresh_button = QPushButton("누락 항목 다시 찾기"); controls.addWidget(self.refresh_button); controls.addStretch(1)
        self.table = QTableWidget(); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False); layout.addWidget(self.table, 1)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(120); layout.addWidget(self.detail)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.import_button.clicked.connect(self._choose_files); self.query_button.clicked.connect(self.query)
        self.repeated_button.clicked.connect(self.repeated); self.refresh_button.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._show_details); self.table.itemDoubleClicked.connect(self._open_chart)

    def _initialize(self) -> None:
        self.status.setText("PostgreSQL 저장 자료의 최신일을 확인하는 중입니다...")
        self.tasks.submit(self.service.latest_date, on_result=self._initialized, on_error=self._error, channel="initialize")

    def _initialized(self, latest: date | None) -> None:
        value = latest or date.today(); qdate = QDate(value.year, value.month, value.day)
        self.start.setDate(qdate); self.end.setDate(qdate)
        if latest: self.query()
        else: self.status.setText("등록된 자료가 없습니다. PNG/JPG 이미지를 선택해 등록하십시오.")

    def _period(self) -> tuple[date, date] | None:
        start, end = self.start.date().toPyDate(), self.end.date().toPyDate()
        if start <= end: return start, end
        QMessageBox.warning(self, "기간 오류", "시작일은 종료일보다 늦을 수 없습니다.")
        return None

    def query(self) -> None:
        period = self._period()
        if period: self._run(lambda: self.service.query(*period), lambda frame: self._show(frame, f"{period[0]} ~ {period[1]}", self.spec.kind), "query")

    def repeated(self) -> None:
        period = self._period()
        if period and self.spec.kind == "featured":
            self._run(lambda: self.service.repeated(*period), lambda frame: self._show(frame, "기간 중복 종목", "repeated"), "repeated")

    def refresh(self) -> None:
        period = self._period()
        if not period: return
        operation = self.service.refresh_missing if self.spec.kind == "featured" else self.service.refresh
        self._run(lambda: operation(*period), lambda result: self._refreshed(result), "refresh")

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, f"{self.spec.title} 이미지 선택", "", "이미지 (*.png *.jpg *.jpeg *.webp)",
        )
        report_date = self.input_date.date().toPyDate()
        if files: self._run(lambda: self.service.prepare_images(files, report_date), self._preview, "prepare-images")

    def _preview(self, plan) -> None:
        if DailyImagePreviewDialog(plan.rows, self).exec() == QDialog.DialogCode.Accepted:
            self._run(lambda: self.service.commit_images(plan), self._imported, "commit-images")
        else:
            self.status.setText("확정 등록을 취소했습니다. 원본 이미지는 연구자료 보관소에 유지됩니다.")

    def _run(self, operation, done, channel: str) -> None:
        self.tasks.submit(operation, on_result=done, on_error=self._error, channel=channel)

    def _show(self, frame: pd.DataFrame, heading: str, profile: str | None = None) -> None:
        self.frame = frame
        preferred = VISIBLE_COLUMNS.get(profile or self.spec.kind, ())
        columns = [column for column in preferred if column in frame.columns]
        if not columns: columns = list(frame.columns)
        self.table.clear(); self.table.setColumnCount(len(columns)); self.table.setRowCount(len(frame))
        self.table.setHorizontalHeaderLabels([label_for(column) for column in columns])
        for column in range(len(columns)): self.table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for row, values in enumerate(frame[columns].itertuples(index=False, name=None)):
            for column, value in enumerate(values):
                item = QTableWidgetItem(self._text(value, columns[column]))
                item.setTextAlignment(self._alignment(columns[column], value)); self.table.setItem(row, column, item)
        if len(frame): self.table.selectRow(0)
        self.table.resizeColumnsToContents(); self.status.setText(f"{heading} · {len(frame):,}건")

    @staticmethod
    def _text(value, column: str) -> str:
        if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)): return ""
        if isinstance(value, (list, tuple)): return ", ".join(map(str, value))
        if column in {"ticker", "stock_code"}: return str(value).zfill(6)
        if isinstance(value, (date, datetime)): return value.strftime("%Y-%m-%d")
        if isinstance(value, Number):
            decimals = 2 if "pct" in column or "return" in column else 1 if "eok" in column else 0
            return format_number(float(value), decimals)
        return str(value)

    @staticmethod
    def _alignment(column: str, value) -> Qt.AlignmentFlag:
        if column in {"report_date", "trade_date", "db_trade_date", "ticker", "stock_code"}:
            return Qt.AlignmentFlag.AlignCenter
        if isinstance(value, Number) and not isinstance(value, bool):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def _show_details(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self.frame.empty: self.detail.clear(); return
        record = self.frame.iloc[row]
        self.detail.setPlainText("\n".join(f"{label_for(str(column))}: {self._text(value, str(column))}" for column, value in record.items()))

    def _open_chart(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self.frame.empty: return
        record = self.frame.iloc[row]; ticker = record.get("ticker", record.get("stock_code"))
        if not pd.isna(ticker) and str(ticker).strip(): self.chart_requested.emit(str(ticker).zfill(6))

    def _refreshed(self, result) -> None:
        QMessageBox.information(self, "완료", str(result)); self.query()

    def _imported(self, result) -> None:
        dates = ", ".join(value.isoformat() for value in result.dates)
        QMessageBox.information(self, "등록 완료", f"{dates} · {result.row_count:,}건 등록\nDB 일치 {result.matched_count:,}건 · 미확인 {result.unmatched_count:,}건")
        self._initialize()

    def _busy(self, busy: bool) -> None:
        for button in (self.import_button, self.query_button, self.repeated_button, self.refresh_button): button.setEnabled(not busy)
        if busy: self.status.setText("처리 중입니다...")

    def _error(self, trace: str) -> None:
        message = str(trace).splitlines()[-1] if trace else "알 수 없는 오류"
        self.status.setText(message); QMessageBox.critical(self, f"{self.spec.title} 오류", message)
