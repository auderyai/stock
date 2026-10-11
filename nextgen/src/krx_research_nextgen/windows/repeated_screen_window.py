from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from krx_research_nextgen.models.screening import DateRange, RepeatedScreenResult
from krx_research_nextgen.presentation.repeated_screen_table import ALIGNMENTS, HEADERS, row_values
from krx_research_nextgen.workers.task_runner import TaskRunner


class RepeatedScreenWindow(QMainWindow):
    stock_requested = pyqtSignal(str, object)

    def __init__(self, controller, rows: list[RepeatedScreenResult], title: str, period: DateRange, parent=None) -> None:
        super().__init__(parent); self._controller, self._rows, self._tasks = controller, rows, TaskRunner(self)
        self.setWindowTitle(f"기간 내 다빈도 종목 · {title}"); self.resize(1540, 780)
        root = QWidget(); self.setCentralWidget(root); layout = QVBoxLayout(root); top = QHBoxLayout(); layout.addLayout(top)
        heading = QLabel(f"{title} · 기간 {period.start} ~ {period.end} · 2회 이상 {len(rows):,}종목")
        heading.setStyleSheet("font-size:16px;font-weight:700"); top.addWidget(heading, 1)
        self.export_button = QPushButton("결과 엑셀 저장"); self.export_button.clicked.connect(self._export); top.addWidget(self.export_button)
        self.table = QTableWidget(len(rows), len(HEADERS)); self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionsMovable(True)
        for column, header in enumerate(HEADERS): self.table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        flags = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignCenter, "right": Qt.AlignmentFlag.AlignRight}
        for row, result in enumerate(rows):
            for column, value in enumerate(row_values(result)):
                item = QTableWidgetItem(value); item.setTextAlignment(flags[ALIGNMENTS[column]] | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.itemDoubleClicked.connect(lambda _: self._open_chart()); layout.addWidget(self.table, 1)
        self.status = QLabel("종목을 더블클릭하면 기존 방식으로 차트를 표시합니다."); layout.addWidget(self.status)
        if rows: self.table.selectRow(0)
        for column, width in enumerate((85, 85, 135, 170, 300, 105, 105, 105, 105, 145)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(True)

    def _open_chart(self) -> None:
        row = self.table.currentRow()
        if row >= 0: self.stock_requested.emit(self.table.item(row, 1).text(), self.navigation())

    def navigation(self) -> dict:
        return {
            "title": self.windowTitle(), "headers": HEADERS,
            "items": [{"code": row.stock_code, "values": row_values(row)} for row in self._rows],
            "alignments": ALIGNMENTS,
        }

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "결과 엑셀 저장", "기간내_다빈도_종목.xlsx", "Excel (*.xlsx)")
        if not path: return
        self.export_button.setEnabled(False); self.status.setText("결과 Excel 저장 중입니다...")
        self._tasks.submit(
            lambda: self._controller.export_repeated(self._rows, path),
            on_result=lambda _: self.status.setText(f"결과 엑셀 저장 완료: {path}"),
            on_error=lambda trace: QMessageBox.critical(self, "결과 엑셀 저장 오류", str(trace).splitlines()[-1]),
            on_finished=lambda: self.export_button.setEnabled(True), channel="repeated-export",
        )
