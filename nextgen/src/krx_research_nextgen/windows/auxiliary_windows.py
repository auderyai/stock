from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QSplitter, QVBoxLayout, QWidget

from krx_research_nextgen.presentation.embedded_finplot_widget import EmbeddedFinplotWidget
from krx_research_nextgen.presentation.number_format import format_number
from krx_research_nextgen.widgets.result_table import ResultTable
from krx_research.presentation.table_policy import TablePresentationPolicy


class _Table(ResultTable):
    def __init__(self, headers: tuple[str, ...], *, identity_key: str) -> None:
        self._headers, self._identity_key = headers, identity_key
        centered = tuple(
            f"value_{index}" for index, header in enumerate(headers) if header == "코드"
        )
        super().__init__(
            identity_columns=(identity_key,),
            identity_width=0,
            policy=TablePresentationPolicy(center_columns=centered),
        )

    def fill(self, rows, values) -> None:
        fields = tuple(f"value_{index}" for index in range(len(self._headers)))
        frame = pd.DataFrame(({
            self._identity_key: row[self._identity_key],
            **dict(zip(fields, values(row), strict=True)),
        } for row in rows), columns=(self._identity_key, *fields))
        self.set_frame(
            frame,
            labels={self._identity_key: "코드", **dict(zip(fields, self._headers, strict=True))},
        )
        self.setColumnHidden(0, True)


class InvestorDashboardWindow(QMainWindow):
    stock_requested = pyqtSignal(str, object)
    TABLE_HEADERS = ("순위", "종목명", "순매매(억원)", "일간(%)", "주간(%)", "월간(%)", "거래대금(억원)")

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.setWindowTitle("KOSPI·KOSDAQ 수급 대시보드 · PyQt6"); self.resize(1500, 900)
        host = QWidget(); layout = QVBoxLayout(host); self.setCentralWidget(host)
        self.status = QLabel("LS 수급 자료를 불러오는 중입니다..."); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.grid = QGridLayout(); layout.addLayout(self.grid, 1); self.panels, self._table_rows = {}, {}
        for row, (key, label) in enumerate((("foreign", "외국인"), ("institution", "기관"), ("individual", "개인"))):
            for column, market in enumerate(("KOSPI", "KOSDAQ")):
                group = QGroupBox(f"{label} · {market}"); box = QVBoxLayout(group)
                summary = QLabel(); box.addWidget(summary)
                tables = {}; pair = QHBoxLayout(); box.addLayout(pair, 1)
                for direction in ("순매수", "순매도"):
                    side = QGroupBox(f"{direction} Top 10"); side_box = QVBoxLayout(side)
                    table = _Table(self.TABLE_HEADERS, identity_key="stock_code")
                    table.chartRequested.connect(lambda t=table: self._open_chart(t))
                    side_box.addWidget(table); pair.addWidget(side); tables[direction] = table
                self.panels[(market, key)] = (summary, tables); self.grid.addWidget(group, row, column)

    @staticmethod
    def _number(value, decimals=1) -> str: return format_number(value, decimals, missing="—")

    def render(self, data, start, end) -> None:
        rows, totals = data["rows"], data["totals"]
        for (market, key), (summary, tables) in self.panels.items():
            total = totals.get((market, key), 0.0); summary.setText(f"기간 순수급 합계 {format_number(total, 1)}억원")
            for direction, table in tables.items():
                selected = [x for x in rows if x["market"] == market and x["investor"] == {"foreign":"외국인","institution":"기관","individual":"개인"}[key] and x["direction"] == direction]
                self._table_rows[table] = selected
                table.fill(selected, self._row_values)
        self.status.setText(f"수급 기준일 {start} ~ {end} · 금액 단위: 억원 · 수익률 단위: % · PostgreSQL LS t1702 검증 자료")

    def show_error(self, text: str) -> None: self.status.setText(text)

    def _row_values(self, item) -> tuple:
        return (item["rank"], item["stock_name"], self._number(item["net"]),
                self._number(item["daily_return"], 2), self._number(item["weekly_return"], 2),
                self._number(item["monthly_return"], 2), self._number(item["trading_value_eok"]))

    def _open_chart(self, table) -> None:
        ticker = table.current_ticker()
        if not ticker: return
        self.stock_requested.emit(ticker, table.navigation_payload("수급 대시보드"))


class MarketIndexWindow(QMainWindow):
    index_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.setWindowTitle("종합·업종 지수 · PyQt6 · Finplot"); self.resize(1680, 980)
        splitter = QSplitter(Qt.Orientation.Horizontal); self.setCentralWidget(splitter)
        chart_host = QWidget(); chart_layout = QVBoxLayout(chart_host); self.chart = EmbeddedFinplotWidget(); self.chart.initialize_finplot(); chart_layout.addWidget(self.chart, 1)
        self.status = QLabel("지수 목록을 불러오는 중입니다..."); chart_layout.addWidget(self.status); splitter.addWidget(chart_host)
        self.table = _Table(("시장", "코드", "종합·업종 지수", "기준일", "지수", "당일(%)"), identity_key="index_code"); splitter.addWidget(self.table); splitter.setSizes([1280, 400])
        self.table.currentTickerChanged.connect(self._selected); self._entries = []

    def render_entries(self, entries) -> None:
        self._entries = entries
        self.table.fill(entries, lambda x: (x["market"],x["index_code"],x["index_name"],x["trade_date"],format_number(x["close_price"],2),format_number(x["daily_return"],2,missing="—")))
        self.status.setText(f"종합·업종 지수 {len(entries):,}개 · 행을 선택하십시오.")
        if entries: self.table.selectRow(0)

    def _selected(self, code: str) -> None:
        if code: self.index_requested.emit(code)

    def show_bundle(self, bundle) -> None:
        self.chart.render(bundle, timeframe="D"); self.status.setText(f"{bundle.symbol} · 최근 {len(bundle.frame):,}개 봉")

    def show_error(self, text: str) -> None: self.status.setText(text)
