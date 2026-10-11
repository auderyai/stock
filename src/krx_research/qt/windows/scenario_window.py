from __future__ import annotations

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from krx_research.analytics.indicator_scenario import INDICATORS
from krx_research.qt.presentation.scenario_plotter import ScenarioPlotter
from krx_research.qt.presentation.scenario_presenter import EMA_CHANGE, ScenarioPresenter
from krx_research.qt.widgets.result_table import ResultTable


class ScenarioWindow(QMainWindow):
    """PySide6 view reproducing the workstation's full indicator-scenario UX."""

    runRequested = Signal()
    indicatorViewRequested = Signal(str)

    def __init__(self, daily: pd.DataFrame, ticker: str = "", market: str = "", parent=None):
        super().__init__(parent)
        self.daily = daily.copy(deep=True)
        self.ticker = ticker
        self.market = market
        self._analysis = None
        self._visible_indicator = "전체"
        self._plotter = ScenarioPlotter()
        self.setWindowTitle(f"보조지표 시나리오 · {ticker} · PySide6")
        self.resize(1600, 950)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        controls = QHBoxLayout()
        layout.addLayout(controls)
        controls.addWidget(QLabel("변동시킬 지표"))
        self.indicator = QComboBox(); self.indicator.addItems(tuple(INDICATORS)); controls.addWidget(self.indicator)
        controls.addWidget(QLabel("목표값"))
        self.target = QLineEdit(); self.target.setMaximumWidth(100); controls.addWidget(self.target)
        controls.addWidget(QLabel("도달 기간(거래일)"))
        self.horizon = QLineEdit(); self.horizon.setMaximumWidth(80); controls.addWidget(self.horizon)
        controls.addWidget(QLabel("과거 학습 기간"))
        self.lookback = QLineEdit(); self.lookback.setValidator(QIntValidator(1, 1_000_000, self)); self.lookback.setPlaceholderText("빈칸=전체"); self.lookback.setMaximumWidth(110); controls.addWidget(self.lookback)
        controls.addWidget(QLabel("숫자 직접 입력 · 빈칸은 전체 이력"))
        self.run_button = QPushButton("시나리오 실행"); self.run_button.clicked.connect(self.runRequested.emit); controls.addWidget(self.run_button)
        controls.addStretch(1)

        self.status = QLabel("지표 목표값과 기간을 입력해 시나리오를 실행하세요.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = ResultTable(self, policy=ScenarioPresenter.TABLE_POLICY); layout.addWidget(self.table)
        self.table.setMaximumHeight(135)
        self.training = QLabel("실행 후 학습·검증에 사용한 날짜와 건수를 표시합니다.")
        self.training.setWordWrap(True); layout.addWidget(self.training)

        general = QHBoxLayout(); layout.addLayout(general)
        general.addWidget(QLabel("보조지표 보기"))
        for label in ("전체", *tuple(INDICATORS)[:6]):
            button = QPushButton(label); button.clicked.connect(lambda _=False, name=label: self.indicatorViewRequested.emit(name)); general.addWidget(button)
        general.addStretch(1)
        ema = QHBoxLayout(); layout.addLayout(ema)
        ema.addWidget(QLabel("EMA 전일 대비 변화율"))
        for label in ("EMA 변화율 전체", *EMA_CHANGE):
            button = QPushButton(label); button.clicked.connect(lambda _=False, name=label: self.indicatorViewRequested.emit(name)); ema.addWidget(button)
        ema.addStretch(1)

        self.tabs = QTabWidget(); layout.addWidget(self.tabs, 1)
        price_page, indicator_page = QWidget(), QWidget()
        self.tabs.addTab(price_page, "가격 시나리오")
        self.tabs.addTab(indicator_page, "전체 보조지표 변동")
        price_layout, indicator_layout = QVBoxLayout(price_page), QVBoxLayout(indicator_page)
        self.price_figure = Figure(figsize=(14, 6), dpi=100)
        self.price_canvas = FigureCanvasQTAgg(self.price_figure); price_layout.addWidget(self.price_canvas)
        self.indicator_figure = Figure(figsize=(14, 7), dpi=100)
        self.indicator_canvas = FigureCanvasQTAgg(self.indicator_figure); indicator_layout.addWidget(self.indicator_canvas)
        self.changes = QLabel("실행 후 모든 지표의 현재값과 종료값을 표시합니다.")
        self.changes.setWordWrap(True); indicator_layout.addWidget(self.changes)

        note = QLabel("'AI 지표변경 예상가'는 한 지표를 바꾼 모델 추정치입니다. '목표 도달 가상가격'과 나머지 지표는 가상 종가 경로 및 최근 고저폭·거래량 가정에서 재계산했습니다. 매매 판정은 모델 검증 기준을 충족할 때만 표시합니다.")
        note.setWordWrap(True); layout.addWidget(note)

    def request_values(self) -> tuple[str, str, str, str]:
        return self.indicator.currentText(), self.target.text(), self.horizon.text(), self.lookback.text()

    def set_current_features(self, features: pd.Series) -> None:
        label = self.indicator.currentText()
        column = INDICATORS[label]
        value = features.get(column)
        if pd.notna(value):
            self.target.setPlaceholderText(f"현재 {float(value):.2f}")

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.run_button.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def set_analysis(self, analysis, selected_indicator: str) -> None:
        self._analysis = analysis
        labels = ScenarioPresenter.CHECKPOINT_LABELS
        self.table.set_frame(ScenarioPresenter.checkpoint_frame(analysis), header_labels=labels)
        self.training.setText(ScenarioPresenter.training_text(analysis, len(self.daily)))
        self.status.setText(ScenarioPresenter.status_text(analysis, selected_indicator))
        self._plotter.draw_price(self.price_figure, analysis); self.price_canvas.draw_idle()
        self.show_indicator(self._visible_indicator)

    def show_indicator(self, label: str) -> None:
        self._visible_indicator = label
        self.tabs.setCurrentIndex(1)
        if self._analysis is None:
            return
        try:
            days = int(self.horizon.text()) if self.horizon.text().strip() else 20
        except ValueError:
            days = 20
        summary = self._plotter.draw_indicators(
            self.indicator_figure,
            self._analysis,
            self.indicator.currentText(),
            label,
            days,
        )
        self.changes.setText(summary)
        self.indicator_canvas.draw_idle()
