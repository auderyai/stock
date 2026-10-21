from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QInputDialog, QPushButton, QVBoxLayout, QWidget,
)

from krx_research_nextgen.models.screening import DateRange, RepeatedScreenResult
from krx_research_nextgen.presentation.repeated_screen_table import (
    HEADERS, LABELS, result_frame, row_values,
)
from krx_research_nextgen.workers.task_runner import TaskRunner
from krx_research_nextgen.widgets.result_table import ResultTable


class RepeatedScreenWindow(QMainWindow):
    stock_requested = pyqtSignal(str, object)

    def __init__(self, controller, rows: list[RepeatedScreenResult], title: str, period: DateRange, parent=None) -> None:
        super().__init__(parent); self._controller, self._rows, self._tasks = controller, rows, TaskRunner(self)
        self.setWindowTitle(f"기간 내 다빈도 종목 · {title}"); self.resize(1540, 780)
        root = QWidget(); self.setCentralWidget(root); layout = QVBoxLayout(root); top = QHBoxLayout(); layout.addLayout(top)
        heading = QLabel(f"{title} · 기간 {period.start} ~ {period.end} · 2회 이상 {len(rows):,}종목")
        heading.setStyleSheet("font-size:16px;font-weight:700"); top.addWidget(heading, 1)
        self.export_button = QPushButton("결과 엑셀 저장"); self.export_button.clicked.connect(self._export); top.addWidget(self.export_button)
        self.table = ResultTable()
        self.table.set_frame(result_frame(rows), labels=LABELS)
        self.table.chartRequested.connect(self._open_chart); layout.addWidget(self.table, 1)
        self.status = QLabel("종목을 더블클릭하면 기존 방식으로 차트를 표시합니다."); layout.addWidget(self.status)
        if rows: self.table.selectRow(0)
        for column, width in enumerate((85, 85, 135, 170, 300, 105, 105, 105, 105, 145)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(True)

    def _open_chart(self) -> None:
        ticker = self.table.current_ticker()
        if ticker: self.stock_requested.emit(ticker, self.navigation())

    def navigation(self) -> dict:
        return self.table.navigation_payload(self.windowTitle()) or {
            "title": self.windowTitle(), "headers": HEADERS,
            "items": [], "alignments": (),
        }

    def _export(self) -> None:
        formats = {
            "기존 상세 목록": ("detailed", "기간내_다빈도_종목.xlsx"),
            "횟수별 가로 배치": ("frequency_groups", "기간내_다빈도_종목_횟수별.xlsx"),
        }
        selected, accepted = QInputDialog.getItem(
            self,
            "엑셀 출력 형식",
            "출력 형식을 선택하십시오.",
            tuple(formats),
            0,
            False,
        )
        if not accepted:
            return
        layout, default_name = formats[selected]
        path, _ = QFileDialog.getSaveFileName(self, "결과 엑셀 저장", default_name, "Excel (*.xlsx)")
        if not path: return
        self.export_button.setEnabled(False); self.status.setText("결과 Excel 저장 중입니다...")
        self._tasks.submit(
            lambda: self._controller.export_repeated(self._rows, path, layout=layout),
            on_result=lambda _: self.status.setText(f"{selected} 저장 완료: {path}"),
            on_error=lambda trace: QMessageBox.critical(self, "결과 엑셀 저장 오류", str(trace).splitlines()[-1]),
            on_finished=lambda: self.export_button.setEnabled(True), channel="repeated-export",
        )
