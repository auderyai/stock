from __future__ import annotations
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout


class SecuritySearchPanel(QGroupBox):
    searchRequested = Signal(str)
    chartRequested = Signal(str)
    comparisonRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("종목 검색 · 이동평균 유사배열 기준 종목", parent)
        self._matches: dict[int, dict[str, str]] = {}
        layout = QVBoxLayout(self)
        row = QHBoxLayout(); layout.addLayout(row)
        self.query = QLineEdit(); self.query.setPlaceholderText("종목명 또는 6자리 종목코드")
        self.search_button = QPushButton("종목 찾기")
        row.addWidget(self.query, 1); row.addWidget(self.search_button)
        self.results = QListWidget(); self.results.setMaximumHeight(110); layout.addWidget(self.results)
        self.selected = QLabel("기준 종목: 선택되지 않음"); self.selected.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(self.selected)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        self.chart_button = QPushButton("차트 열기"); self.compare_button = QPushButton("유사배열 기준종목으로 사용")
        buttons.addWidget(self.chart_button); buttons.addWidget(self.compare_button)
        self.search_button.clicked.connect(self._search); self.query.returnPressed.connect(self._search)
        self.chart_button.clicked.connect(lambda: self._emit_selected(self.chartRequested))
        self.compare_button.clicked.connect(lambda: self._emit_selected(self.comparisonRequested))
        self.results.itemDoubleClicked.connect(lambda _item: self._emit_selected(self.chartRequested))

    def _search(self):
        text = self.query.text().strip()
        if text: self.searchRequested.emit(text)

    def set_matches(self, rows: list[dict[str, str]]) -> None:
        self.results.clear(); self._matches.clear()
        for index, row in enumerate(rows):
            ticker = str(row.get("ticker", "")).zfill(6)
            name = str(row.get("name", "")); market = str(row.get("market", ""))
            item = QListWidgetItem(f"{ticker}  {name}  [{market}]")
            self.results.addItem(item); self._matches[index] = {"ticker": ticker, "name": name, "market": market}
        if rows: self.results.setCurrentRow(0)

    def selected_ticker(self) -> str | None:
        row = self.results.currentRow(); value = self._matches.get(row)
        return None if value is None else value["ticker"]

    def set_comparison(self, ticker: str, name: str = "") -> None:
        self.selected.setText(f"기준 종목: {ticker} {name}".strip())
        self.selected.setProperty("ticker", ticker)

    def comparison_ticker(self) -> str | None:
        value = self.selected.property("ticker")
        return str(value) if value else None

    def _emit_selected(self, signal) -> None:
        ticker = self.selected_ticker() or self.query.text().strip()
        if ticker: signal.emit(ticker)
