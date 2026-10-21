from __future__ import annotations
import datetime as dt
from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel,
    QPushButton, QWidget, QVBoxLayout,
)
from krx_research.collectors.realtime_quotes import QUOTE_VENUES
from krx_research.qt.models.screen_query import ScreenQuery
from krx_research.qt.widgets.rank_limit_control import RankLimitControl
from krx_research.policies.workstation_options import DATABASE_SOURCE_MODE, REALTIME_SOURCE_MODE

class QueryPanel(QWidget):
    queryChanged = Signal()
    near52wRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        box = QGroupBox("조회 조건")
        grid = QGridLayout(box)
        self.source = QComboBox(); self.source.addItem("데이터베이스", DATABASE_SOURCE_MODE); self.source.addItem("실시간", REALTIME_SOURCE_MODE)
        self.venue = QComboBox()
        for venue in sorted(QUOTE_VENUES): self.venue.addItem("KRX+NXT" if venue == "COMBINED" else venue, venue)
        self.start_date = QDateEdit(calendarPopup=True); self.end_date = QDateEdit(calendarPopup=True)
        self.rank_limit = RankLimitControl(50)
        for row, (label, widget) in enumerate((("자료", self.source), ("시장", self.venue), ("시작", self.start_date), ("종료", self.end_date), ("출력 순위", self.rank_limit))):
            grid.addWidget(QLabel(label), row, 0); grid.addWidget(widget, row, 1)
        root.addWidget(box)

        distance_box = QGroupBox("52주 최고가 대비 종가 (%)")
        distance_grid = QGridLayout(distance_box)
        self.near_low = QDoubleSpinBox(); self.near_low.setRange(-100, 100); self.near_low.setDecimals(2); self.near_low.setValue(-10); self.near_low.setSuffix(" %")
        self.near_high = QDoubleSpinBox(); self.near_high.setRange(-100, 100); self.near_high.setDecimals(2); self.near_high.setValue(0); self.near_high.setSuffix(" %")
        distance_grid.addWidget(self.near_low, 0, 0)
        distance_grid.addWidget(QLabel("~"), 0, 1)
        distance_grid.addWidget(self.near_high, 0, 2)
        self.near_search = QPushButton("구간 검색")
        distance_grid.addWidget(self.near_search, 0, 3)
        root.addWidget(distance_box)
        for widget in (self.source,self.venue): widget.currentIndexChanged.connect(self.queryChanged)
        for widget in (self.start_date,self.end_date): widget.dateChanged.connect(self.queryChanged)
        for widget in (self.near_low, self.near_high): widget.valueChanged.connect(self.queryChanged)
        self.near_low.lineEdit().returnPressed.connect(self._request_near52w)
        self.near_high.lineEdit().returnPressed.connect(self._request_near52w)
        self.near_search.clicked.connect(self._request_near52w)
        self.rank_limit.valueChanged.connect(self.queryChanged)


    def _request_near52w(self) -> None:
        if float(self.near_low.value()) > float(self.near_high.value()):
            return
        self.near52wRequested.emit()

    def set_dates(self, value: dt.date) -> None:
        q = QDate(value.year, value.month, value.day); self.start_date.setDate(q); self.end_date.setDate(q)

    def quote_venue(self) -> str: return str(self.venue.currentData() or "KRX")

    def selected_dates(self) -> tuple[dt.date, dt.date]:
        return self.start_date.date().toPython(), self.end_date.date().toPython()

    def build_query(self, screen_key: str, *, comparison_ticker: str | None = None) -> ScreenQuery:
        return ScreenQuery(screen_key=screen_key, start_date=self.start_date.date().toPython(), end_date=self.end_date.date().toPython(), source_mode=str(self.source.currentData()), quote_venue=self.quote_venue(), near_52w_low=float(self.near_low.value()), near_52w_high=float(self.near_high.value()), comparison_ticker=comparison_ticker, top_n=self.rank_limit.value())
