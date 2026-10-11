from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from krx_research.qt.presentation.investor_presenter import InvestorFlowPresenter
from krx_research.qt.models.investor_dashboard import INVESTORS, InvestorDashboardData
from krx_research.qt.widgets.result_table import ResultTable
from krx_research.qt.widgets.rank_limit_control import RankLimitControl


class InvestorDashboardView(QMainWindow):
    """Pure PySide6 investor-flow view.

    It owns widgets and emits user intent only.  Data shaping, validation and
    PostgreSQL access live outside this class.
    """

    queryRequested = Signal(object, object, int)
    chartRequested = Signal(str, object, object)

    def __init__(self, parent=None, start: dt.date | None = None, end: dt.date | None = None):
        super().__init__(parent)
        self._presenter = InvestorFlowPresenter()
        self.setWindowTitle("KOSPI·KOSDAQ 수급 순위 · PySide6")
        self.resize(1500, 900)
        host = QWidget()
        self.setCentralWidget(host)
        layout = QVBoxLayout(host)

        controls = QHBoxLayout()
        layout.addLayout(controls)
        controls.addWidget(QLabel("시작"))
        self.start = QDateEdit(calendarPopup=True)
        controls.addWidget(self.start)
        controls.addWidget(QLabel("종료"))
        self.end = QDateEdit(calendarPopup=True)
        controls.addWidget(self.end)
        self.rank_limit = RankLimitControl(10)
        controls.addWidget(self.rank_limit)
        button = QPushButton("조회")
        button.clicked.connect(self._request)
        controls.addWidget(button)
        controls.addStretch(1)

        self.status = QLabel("수급 DB 기간 조회 준비")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.grid = QGridLayout()
        layout.addLayout(self.grid, 1)

        today = dt.date.today()
        a = start or today
        b = end or a
        self.start.setDate(QDate(a.year, a.month, a.day))
        self.end.setDate(QDate(b.year, b.month, b.day))

    def initialize(self) -> None:
        self._request()

    def _request(self) -> None:
        self.queryRequested.emit(self.start.date().toPython(), self.end.date().toPython(), self.rank_limit.value())

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def render(self, result: InvestorDashboardData) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        used = ", ".join(day.isoformat() for day in result.actual_days)
        self.status.setText(
            f"{result.requested_start} ~ {result.requested_end} · 실제 LS 적재 "
            f"{len(result.actual_days)}일 [{used}]"
        )

        for col, market in enumerate(("KOSPI", "KOSDAQ")):
            for row, (investor, title) in enumerate(INVESTORS.items()):
                group = QGroupBox(f"{market} · {title}")
                box = QVBoxLayout(group)
                top_n = self.rank_limit.value()
                for direction, label in (("buy", f"순매수 Top {top_n}"), ("sell", f"순매도 Top {top_n}")):
                    table = ResultTable()
                    presented = self._presenter.present(
                        result.rankings[(market, investor, direction)].copy()
                    )
                    table.set_frame(presented.frame, header_labels=presented.labels)
                    labels = dict(presented.labels)
                    table.chartRequested.connect(
                        lambda t=table, l=labels: self._emit_chart(t, l)
                    )
                    box.addWidget(QLabel(label))
                    box.addWidget(table)
                self.grid.addWidget(group, row, col)

    def _emit_chart(self, table: ResultTable, labels: dict[str, str]) -> None:
        ticker = table.current_ticker()
        if ticker:
            self.chartRequested.emit(ticker, table.frame.copy(deep=False), labels)
