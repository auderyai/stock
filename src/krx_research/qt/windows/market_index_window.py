from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMainWindow, QSplitter, QVBoxLayout, QWidget

from krx_research.qt.presentation.table_policy import TablePresentationPolicy
from krx_research.qt.widgets.chart_controls import ChartControlPanel, ClassicStrategyPanel
from krx_research.qt.widgets.result_table import ResultTable
from krx_research.ui.charts import build_chart_figure
from krx_research.ui.on_demand import TIMEFRAME_LABELS


_INDEX_HEADERS = {
    "market": "시장", "index_code": "코드", "index_name": "종합·업종 지수",
    "level": "지수", "daily_return": "당일 등락률", "weekly_return": "주간 등락률",
    "trading_value_eok": "당일 거래대금(억원)",
    "previous_trading_value_eok": "전일 거래대금(억원)",
}


class MarketIndexView(QMainWindow):
    """Pure PySide6 composite/sector-index view."""

    indexRequested = Signal(str)
    strategyRefreshRequested = Signal(object, object)
    scenarioRequested = Signal()

    def __init__(self, parent=None, *, navigate: bool = True):
        super().__init__(parent)
        self.navigate = bool(navigate)
        self.dataset = None
        self.canvas = None
        self._build()

    def _build(self) -> None:
        self.resize(1680 if self.navigate else 1500, 980)
        self.setWindowTitle("코스피·코스닥 종합·업종 지수 · PySide6")
        host = QWidget(self)
        self.setCentralWidget(host)
        root = QVBoxLayout(host)

        top = QHBoxLayout(); root.addLayout(top)
        if not self.navigate:
            top.addWidget(QLabel("지수"))
            self.combo = QComboBox()
            self.combo.currentIndexChanged.connect(self._combo_changed)
            top.addWidget(self.combo, 1)
        else:
            self.combo = None
            top.addWidget(QLabel("종합·업종 지수 · ↑↓ 또는 클릭으로 차트 이동"), 1)

        self.content = QSplitter(Qt.Horizontal)
        root.addWidget(self.content, 1)
        chart_host = QWidget()
        self.chart_layout = QVBoxLayout(chart_host)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        self.content.addWidget(chart_host)

        if self.navigate:
            policy = TablePresentationPolicy(
                ticker_columns=("index_code",), code_width=0,
                center_columns=("index_code",),
                right_columns=("level", "daily_return", "weekly_return", "trading_value_eok", "previous_trading_value_eok"),
            )
            self.index_table = ResultTable(policy=policy, identity_columns=("index_code",), identity_width=0)
            self.index_table.currentTickerChanged.connect(self.indexRequested.emit)
            self.content.addWidget(self.index_table)
            self.content.setSizes([1280, 400])
        else:
            self.index_table = None

        self.controls = ChartControlPanel(default_days=800, include_investor=False)
        self.controls.redrawRequested.connect(self.redraw)
        self.controls.scenarioRequested.connect(self.scenarioRequested.emit)
        root.addWidget(self.controls)
        self.strategy_panel = ClassicStrategyPanel()
        root.addWidget(self.strategy_panel)
        self.status = QLabel("지수 목록을 불러오는 중입니다...")
        root.addWidget(self.status)

    def set_entries(self, entries: list[dict], overview) -> None:
        if self.navigate:
            self.index_table.set_frame(overview, header_labels=_INDEX_HEADERS)
            if not overview.empty:
                self.index_table.select_ticker(str(overview.iloc[0]["index_code"]))
            return
        self.combo.blockSignals(True)
        self.combo.clear()
        for entry in entries:
            code = str(entry.get("index_code") or "")
            name = "KOSPI 종합" if code == "1001" else "KOSDAQ 종합" if code == "2001" else f"{entry.get('market')} · {entry.get('index_name')}"
            self.combo.addItem(f"{name} ({code})", code)
        self.combo.blockSignals(False)
        if entries:
            self.combo.setCurrentIndex(0)
            self.indexRequested.emit(str(entries[0]["index_code"]))

    def _combo_changed(self, _index: int) -> None:
        if self.combo is not None and self.combo.currentData():
            self.indexRequested.emit(str(self.combo.currentData()))

    def set_dataset(self, dataset, assessments=()) -> None:
        self.dataset = dataset
        self.strategy_panel.set_assessments(assessments)
        self.redraw()

    def set_strategy_assessments(self, assessments) -> None:
        self.strategy_panel.set_assessments(assessments)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def redraw(self, *_args) -> None:
        if self.dataset is None:
            return
        while self.chart_layout.count():
            item = self.chart_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        options = self.controls.options()
        figure = build_chart_figure(
            self.dataset,
            self.controls.days_value(),
            profile_bins=self.controls.profile_bins.value(),
            options=options,
        )
        self.canvas = FigureCanvasQTAgg(figure)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.chart_layout.addWidget(self.canvas)
        self.canvas.draw_idle()
        bars = self.dataset.bars(options.timeframe)
        count = len(bars) if self.controls.days_value() is None else min(self.controls.days_value(), len(bars))
        mode = "전체기간" if self.controls.days_value() is None else f"최근 {count:,}개 봉"
        self.status.setText(f"{self.dataset.name} ({self.dataset.ticker}) · {TIMEFRAME_LABELS[options.timeframe]} · {mode}")
        self.strategyRefreshRequested.emit(self.dataset, self.controls.days_value())
