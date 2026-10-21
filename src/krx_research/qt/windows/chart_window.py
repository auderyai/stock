from __future__ import annotations

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QMainWindow, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from krx_research.qt.presentation.chart_navigation_policy import CHART_NAVIGATION_TABLE_POLICY
from krx_research.qt.widgets.chart_controls import ChartControlPanel, ClassicStrategyPanel
from krx_research.qt.widgets.result_table import ResultTable
from krx_research.ui.charts import build_chart_figure
from krx_research.policies.workstation_options import TIMEFRAME_LABELS


class ChartWindow(QMainWindow):
    """Pure PySide6 chart view.

    In synchronized mode the right pane owns the current screen result list.
    Row selection and Up/Down keyboard navigation emit a ticker signal; data
    loading stays in ChartController.
    """

    reloadRequested = Signal()
    scenarioRequested = Signal()
    navigationTickerChanged = Signal(str)

    def __init__(self, ticker: str, *, quote_venue: str = "KRX", navigation_enabled: bool = False, parent=None):
        super().__init__(parent)
        self.ticker = str(ticker).strip()
        self.quote_venue = quote_venue
        self.dataset = None
        self.strategy_assessments = ()
        self.canvas = None
        self._children = []
        self._navigation_enabled = bool(navigation_enabled)
        self._navigation_guard = False
        self.setWindowTitle(f"KRX 차트 · {self.ticker}")
        self.resize(1680, 980)
        self._build()

    def _build(self) -> None:
        splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(splitter)

        chart_page = QWidget(splitter)
        layout = QVBoxLayout(chart_page)
        self.chart_host = QVBoxLayout()
        layout.addLayout(self.chart_host, 1)

        insight = QHBoxLayout(); layout.addLayout(insight)
        self.strategy_panel = ClassicStrategyPanel()
        insight.addWidget(self.strategy_panel, 5)

        reason_box = QGroupBox("당일 상승 사유")
        reason_layout = QVBoxLayout(reason_box)
        self.reason_text = QTextEdit(); self.reason_text.setReadOnly(True); self.reason_text.setMaximumHeight(92)
        self.reason_text.setPlainText("상승 사유는 별도 뉴스 조회 기능에서 확인할 수 있습니다.")
        reason_layout.addWidget(self.reason_text)
        insight.addWidget(reason_box, 7)

        self.controls = ChartControlPanel(default_days=500, include_investor=True)
        self.controls.redrawRequested.connect(self.redraw)
        self.controls.scenarioRequested.connect(self.scenarioRequested.emit)
        layout.addWidget(self.controls)
        self.status = QLabel("차트 자료를 불러오는 중입니다..."); layout.addWidget(self.status)

        splitter.addWidget(chart_page)

        self.navigation_page = QWidget(splitter)
        navigation_layout = QVBoxLayout(self.navigation_page)
        navigation_title = QLabel("조회 결과 종목")
        navigation_title.setStyleSheet("font-size:14px;font-weight:700")
        navigation_layout.addWidget(navigation_title)
        self.navigation_table = ResultTable(policy=CHART_NAVIGATION_TABLE_POLICY)
        self.navigation_table.currentTickerChanged.connect(self._navigation_changed)
        navigation_layout.addWidget(self.navigation_table, 1)
        splitter.addWidget(self.navigation_page)
        self.navigation_page.setVisible(self._navigation_enabled)
        splitter.setSizes([1360, 320] if self._navigation_enabled else [1680, 0])

    def set_navigation_enabled(self, enabled: bool) -> None:
        self._navigation_enabled = bool(enabled)
        self.navigation_page.setVisible(self._navigation_enabled)

    def set_navigation_results(self, frame: pd.DataFrame, labels: dict[str, str], *, selected_ticker: str | None = None) -> None:
        self.set_navigation_enabled(True)
        self._navigation_guard = True
        try:
            self.navigation_table.set_frame(frame, header_labels=labels)
            if selected_ticker:
                self.select_navigation_ticker(selected_ticker)
        finally:
            self._navigation_guard = False

    def select_navigation_ticker(self, ticker: str) -> None:
        self._navigation_guard = True
        try:
            self.navigation_table.select_ticker(ticker)
        finally:
            self._navigation_guard = False

    def _navigation_changed(self, ticker: str) -> None:
        if self._navigation_enabled and not self._navigation_guard:
            self.navigationTickerChanged.emit(ticker)

    def keep_child(self, window) -> None:
        self._children.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._children.remove(w) if w in self._children else None)

    def set_loading(self, text: str) -> None:
        self.status.setText(text)

    def set_dataset(self, dataset, assessments=()) -> None:
        self.dataset = dataset
        self.strategy_assessments = tuple(assessments or ())
        self.ticker = dataset.ticker
        self.setWindowTitle(f"{dataset.name} ({dataset.ticker}) · {dataset.market} · PySide6")
        self.strategy_panel.set_assessments(self.strategy_assessments)
        self.redraw()

    def redraw(self, *_args) -> None:
        if self.dataset is None:
            return
        while self.chart_host.count():
            item = self.chart_host.takeAt(0); widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        figure = build_chart_figure(
            self.dataset,
            self.controls.days_value(),
            profile_bins=self.controls.profile_bins.value(),
            options=self.controls.options(),
        )
        self.canvas = FigureCanvasQTAgg(figure)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.chart_host.addWidget(self.canvas)
        self.canvas.draw_idle()
        options = self.controls.options()
        bars = self.dataset.bars(options.timeframe)
        requested = self.controls.days_value()
        visible = len(bars) if requested is None else min(requested, len(bars))
        mode = "전체기간" if requested is None else f"최근 {visible:,}개 봉"
        self.status.setText(f"{self.dataset.name} ({self.dataset.ticker}) · {TIMEFRAME_LABELS[options.timeframe]} · {mode} · {self.dataset.market} · {self.dataset.industry}")
