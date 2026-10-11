from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)
from krx_research.qt.widgets.query_panel import QueryPanel
from krx_research.qt.widgets.result_table import ResultTable
from krx_research.qt.widgets.screen_selector import ScreenSelector
from krx_research.qt.widgets.security_search_panel import SecuritySearchPanel
from krx_research.qt.widgets.assistant_panel import AssistantPanel


class WorkstationWindow(QMainWindow):
    """Pure PySide6 view. No database access and no business calculations."""

    runRequested = Signal()
    exportRequested = Signal()
    chartRequested = Signal()
    investorRequested = Signal()
    marketIndexRequested = Signal()
    featuredRequested = Signal()
    themeRequested = Signal()
    researchArchiveRequested = Signal()
    synchronizedChartRequested = Signal(str)
    securitySearchRequested = Signal(str)
    directChartRequested = Signal(str)
    comparisonTickerRequested = Signal(str)
    near52wRequested = Signal()
    assistantRequested = Signal(str)
    assistantClearRequested = Signal()
    assistantCodeLibraryRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KRX Stock · PySide6 · PostgreSQL")
        self.resize(1720, 1000)
        self._build()

    def _build(self) -> None:
        splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        title = QLabel("Stock · PySide6")
        title.setStyleSheet("font-size:18px;font-weight:700")
        left_layout.addWidget(title)
        note = QLabel("데이터베이스: PostgreSQL 전용 · C:\\stock\\.env 기준")
        note.setWordWrap(True)
        left_layout.addWidget(note)

        self.query_panel = QueryPanel()
        self.query_panel.near52wRequested.connect(self.near52wRequested.emit)
        left_layout.addWidget(self.query_panel)
        self.security_search = SecuritySearchPanel()
        left_layout.addWidget(self.security_search)
        self.screen_selector = ScreenSelector()
        left_layout.addWidget(self.screen_selector, 1)

        buttons = QGridLayout()
        self.run_button = QPushButton("선택 항목 조회 실행")
        buttons.addWidget(self.run_button, 0, 0, 1, 2)
        actions = (
            ("수급 대시보드", self.investorRequested),
            ("종합·업종 지수", self.marketIndexRequested),
            ("일일 특징주", self.featuredRequested),
            ("일일 테마", self.themeRequested),
            ("리포트·이미지 자료", self.researchArchiveRequested),
        )
        for pos, (label, signal) in enumerate(actions):
            button = QPushButton(label)
            button.clicked.connect(signal.emit)
            buttons.addWidget(button, 1 + pos // 2, pos % 2)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        top = QHBoxLayout()
        self.heading = QLabel("스크리닝 항목을 선택하십시오.")
        self.heading.setStyleSheet("font-size:15px;font-weight:700")
        top.addWidget(self.heading, 1)
        self.sync_chart = QCheckBox("결과목록 탐색 · 같은 차트 갱신")
        top.addWidget(self.sync_chart)
        self.export_button = QPushButton("결과 엑셀 저장")
        self.chart_button = QPushButton("선택 종목 차트")
        top.addWidget(self.export_button)
        top.addWidget(self.chart_button)
        right_layout.addLayout(top)

        content = QSplitter(Qt.Vertical)
        self.result_table = ResultTable()
        content.addWidget(self.result_table)
        self.assistant_panel = AssistantPanel()
        content.addWidget(self.assistant_panel)
        content.setSizes([650, 250])
        right_layout.addWidget(content, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        right_layout.addWidget(self.status)
        splitter.addWidget(right)
        splitter.setSizes([450, 1270])

        self.run_button.clicked.connect(self.runRequested.emit)
        self.screen_selector.executeRequested.connect(self.runRequested.emit)
        self.export_button.clicked.connect(self.exportRequested.emit)
        self.chart_button.clicked.connect(self.chartRequested.emit)
        self.result_table.chartRequested.connect(self.chartRequested.emit)
        self.result_table.currentTickerChanged.connect(self._ticker_changed)
        self.security_search.searchRequested.connect(self.securitySearchRequested.emit)
        self.security_search.chartRequested.connect(self.directChartRequested.emit)
        self.security_search.comparisonRequested.connect(self.comparisonTickerRequested.emit)
        self.assistant_panel.submitted.connect(self.assistantRequested.emit)
        self.assistant_panel.clearRequested.connect(self.assistantClearRequested.emit)
        self.assistant_panel.codeLibraryRequested.connect(self.assistantCodeLibraryRequested.emit)

    def synchronized_chart_enabled(self) -> bool:
        return self.sync_chart.isChecked()

    def _ticker_changed(self, ticker: str) -> None:
        if self.sync_chart.isChecked():
            self.synchronizedChartRequested.emit(ticker)

    def set_busy(self, busy: bool) -> None:
        self.run_button.setEnabled(not busy)
        if busy:
            self.status.setText("조회 중입니다...")

    def show_dataset(self, frame, labels: dict[str, str], heading: str, status: str) -> None:
        self.result_table.set_frame(frame, header_labels=labels)
        self.heading.setText(heading)
        self.status.setText(status)

    def set_search_results(self, rows: list[dict[str, str]]) -> None:
        self.security_search.set_matches(rows)
        self.status.setText(f"종목 검색 결과 {len(rows):,}건")

    def set_comparison_ticker(self, ticker: str, name: str = "") -> None:
        self.security_search.set_comparison(ticker, name)
        self.status.setText(f"이동평균 유사배열 기준 종목: {ticker} {name}".strip())

    def comparison_ticker(self) -> str | None:
        return self.security_search.comparison_ticker()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_assistant_busy(self, busy: bool) -> None:
        self.assistant_panel.set_busy(busy)
        self.status.setText("AI가 DB·파일·웹 자료를 확인 중입니다..." if busy else self.status.text())

    def show_assistant_reply(self, text: str, citations=()) -> None:
        self.assistant_panel.append_message("AI", text, citations)

    def clear_assistant(self) -> None:
        self.assistant_panel.clear()
