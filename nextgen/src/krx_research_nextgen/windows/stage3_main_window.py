from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from krx_research_nextgen.controllers.main_window_controller import MainWindowController
from krx_research_nextgen.models.security import SecurityRecord
from krx_research_nextgen.presentation.embedded_finplot_widget import EmbeddedFinplotWidget
from krx_research_nextgen.widgets.result_table import ResultTable


class Stage3MainWindow(QMainWindow):
    def __init__(self, controller: MainWindowController) -> None:
        super().__init__()
        self._controller = controller
        self._records: list[SecurityRecord] = []
        self._current_code = ""
        self._chart_limit = 550

        self.setWindowTitle("C:\\stock NextGen - Finplot Stage 3")
        self.resize(1700, 950)

        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("종목명 또는 종목코드 검색")
        self.search_edit.setClearButtonEnabled(True)
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        header.addWidget(QLabel("검색"))
        header.addWidget(self.search_edit, 1)
        header.addWidget(self.status_label)
        root_layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        self.table = ResultTable()
        self.table.setColumnWidth(0, 85)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 70)
        splitter.addWidget(self.table)

        self.chart = EmbeddedFinplotWidget()
        splitter.addWidget(self.chart)
        splitter.setSizes([330, 1370])

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)

        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(120)

        self.search_edit.textChanged.connect(self._search_timer.start)
        self.search_edit.returnPressed.connect(self._search_now)
        self._search_timer.timeout.connect(self._search_now)

        self.table.currentTickerChanged.connect(lambda _ticker: self._selection_timer.start())
        self.table.chartRequested.connect(self._chart_now)
        self._selection_timer.timeout.connect(self._chart_now)

        self._load_status()
        self._search_now()
        self.chart.initialize_finplot()

    def _load_status(self) -> None:
        try:
            s = self._controller.status()
            self.status_label.setText(
                f"DB {s.get('database')} | "
                f"OHLCV {s.get('ohlcv_relation')} | "
                f"MASTER {s.get('security_relation')}"
            )
        except Exception as exc:
            self.status_label.setText(f"상태 확인 실패: {exc}")

    def _search_now(self) -> None:
        try:
            self._records = self._controller.search_securities(
                self.search_edit.text().strip(),
                limit=300,
            )
            self._populate_table(self._records)
            self.statusBar().showMessage(f"검색 결과 {len(self._records)}개")
        except Exception as exc:
            self._show_error("종목 검색 오류", exc)

    def _populate_table(self, records: list[SecurityRecord]) -> None:
        frame = pd.DataFrame(
            ({"stock_code": item.stock_code, "stock_name": item.stock_name, "market": item.market}
             for item in records),
            columns=("stock_code", "stock_name", "market"),
        )
        self.table.set_frame(frame, labels={"stock_code": "종목코드", "stock_name": "종목명", "market": "시장"})

        if records:
            self._selection_timer.start()

    def _selected_code(self) -> str | None:
        return self.table.current_ticker()

    def _chart_now(self) -> None:
        code = self._selected_code()
        if not code or code == self._current_code:
            return

        try:
            self.statusBar().showMessage(f"{code} 차트 조회 중...")
            bundle = self._controller.prepare_chart(code, limit=self._chart_limit)
            self.chart.render(bundle)
            self._current_code = code

            self.setWindowTitle("C:\\stock NextGen · Stock 차트")
            self.statusBar().showMessage(
                f"{bundle.symbol} | 최근 {len(bundle.frame)} 거래일",
                5000,
            )
        except Exception as exc:
            self._show_error(f"{code} 차트 오류", exc)

    def _show_error(self, title: str, exc: Exception) -> None:
        self.statusBar().showMessage(str(exc), 10000)
        QMessageBox.critical(self, title, str(exc))
