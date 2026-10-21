from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtWidgets import (
    QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from krx_research.qt.presentation.column_catalog import label_for
from krx_research_nextgen.controllers.daily_research_controller import DailyResearchController
from krx_research_nextgen.workers.task_runner import TaskRunner
from krx_research_nextgen.widgets.result_table import ResultTable


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
        columns = [key for key, _ in PREVIEW_COLUMNS]
        table = ResultTable()
        table.set_frame(
            pd.DataFrame(rows).reindex(columns=columns),
            labels=dict(PREVIEW_COLUMNS),
        )
        table.setColumnWidth(10, 480); layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("확정 등록")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class DailyResearchWindow(QMainWindow):
    """PyQt6 view for the shared, Qt-free daily research services."""

    chart_requested = pyqtSignal(str)

    def __init__(self, kind: str, controller: DailyResearchController, parent=None) -> None:
        super().__init__(parent)
        self.spec = SPECS[kind]
        self.controller = controller
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
        self.table = ResultTable(); layout.addWidget(self.table, 1)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(120); layout.addWidget(self.detail)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.import_button.clicked.connect(self._choose_files); self.query_button.clicked.connect(self.query)
        self.repeated_button.clicked.connect(self.repeated); self.refresh_button.clicked.connect(self.refresh)
        self.table.selectionModel().currentRowChanged.connect(self._show_details)
        self.table.chartRequested.connect(self._open_chart)

    def _initialize(self) -> None:
        self.status.setText("PostgreSQL 저장 자료의 최신일을 확인하는 중입니다...")
        self.tasks.submit(self.controller.latest_date, on_result=self._initialized, on_error=self._error, channel="initialize")

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
        if period: self._run(lambda: self.controller.query(*period), lambda frame: self._show(frame, f"{period[0]} ~ {period[1]}", self.spec.kind), "query")

    def repeated(self) -> None:
        period = self._period()
        if period and self.spec.kind == "featured":
            self._run(lambda: self.controller.repeated(*period), lambda frame: self._show(frame, "기간 중복 종목", "repeated"), "repeated")

    def refresh(self) -> None:
        period = self._period()
        if not period: return
        self._run(lambda: self.controller.refresh(*period), lambda result: self._refreshed(result), "refresh")

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, f"{self.spec.title} 이미지 선택", "", "이미지 (*.png *.jpg *.jpeg *.webp)",
        )
        report_date = self.input_date.date().toPyDate()
        if files: self._run(lambda: self.controller.prepare_images(files, report_date), self._preview, "prepare-images")

    def _preview(self, plan) -> None:
        if DailyImagePreviewDialog(plan.rows, self).exec() == QDialog.DialogCode.Accepted:
            self._run(lambda: self.controller.commit_images(plan), self._imported, "commit-images")
        else:
            self.status.setText("확정 등록을 취소했습니다. 원본 이미지는 연구자료 보관소에 유지됩니다.")

    def _run(self, operation, done, channel: str) -> None:
        self.tasks.submit(operation, on_result=done, on_error=self._error, channel=channel)

    def _show(self, frame: pd.DataFrame, heading: str, profile: str | None = None) -> None:
        preferred = VISIBLE_COLUMNS.get(profile or self.spec.kind, ())
        columns = [column for column in preferred if column in frame.columns]
        if not columns: columns = list(frame.columns)
        visible = frame.loc[:, columns].copy()
        self.frame = visible
        self.table.set_frame(visible, labels={column: label_for(column) for column in columns})
        self.status.setText(f"{heading} · {len(frame):,}건")

    def _show_details(self) -> None:
        record = self.table.current_record()
        if not record: self.detail.clear(); return
        self.detail.setPlainText(
            "\n".join(f"{label_for(str(column))}: {value}" for column, value in record.items())
        )

    def _open_chart(self) -> None:
        ticker = self.table.current_ticker()
        if ticker: self.chart_requested.emit(ticker)

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
