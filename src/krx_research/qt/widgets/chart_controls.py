from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from krx_research.ui.chart_options import ChartDisplayOptions
from krx_research.ui.charts import DEFAULT_PROFILE_BINS, MAX_PROFILE_BINS, MIN_PROFILE_BINS
from krx_research.ui.classic_strategies import ALL_STRATEGIES, STRATEGY_OPTIONS, format_strategy_assessments
from krx_research.ui.on_demand import TIMEFRAME_LABELS


class ChartControlPanel(QGroupBox):
    """Reusable PySide6 chart controls shared by stock and index charts."""

    redrawRequested = Signal()
    scenarioRequested = Signal()

    def __init__(self, parent=None, *, default_days: int = 500, include_investor: bool = True):
        super().__init__("차트 표시 선택", parent)
        self._include_investor = bool(include_investor)
        self._build(default_days)

    def _build(self, default_days: int) -> None:
        row = QHBoxLayout(self)
        row.addWidget(QLabel("봉 주기"))
        self.timeframe = QComboBox()
        for key, label in TIMEFRAME_LABELS.items():
            self.timeframe.addItem(label, key)
        self.timeframe.currentIndexChanged.connect(self.redrawRequested.emit)
        row.addWidget(self.timeframe)

        row.addWidget(QLabel("표시 봉수"))
        self.days = QSpinBox()
        self.days.setRange(0, 100_000)
        self.days.setValue(max(0, int(default_days)))
        self.days.setSpecialValueText("전체")
        row.addWidget(self.days)

        row.addWidget(QLabel("매물대 구간"))
        self.profile_bins = QSpinBox()
        self.profile_bins.setRange(MIN_PROFILE_BINS, MAX_PROFILE_BINS)
        self.profile_bins.setValue(DEFAULT_PROFILE_BINS)
        self.profile_bins.valueChanged.connect(self.redrawRequested.emit)
        row.addWidget(self.profile_bins)

        apply_button = QPushButton("적용")
        apply_button.clicked.connect(self.redrawRequested.emit)
        row.addWidget(apply_button)
        full_button = QPushButton("전체기간")
        full_button.clicked.connect(self._full_period)
        row.addWidget(full_button)
        scenario_button = QPushButton("보조지표 시나리오·AI")
        scenario_button.clicked.connect(self.scenarioRequested.emit)
        row.addWidget(scenario_button)

        self.flags: dict[str, QCheckBox] = {}
        flag_specs = [
            ("volume", "거래량", True),
            ("rsi", "RSI(14,9)", True),
            ("macd", "MACD 오실레이터", True),
            ("stochastic", "스토캐스틱 슬로우(5,3,3)", True),
        ]
        if self._include_investor:
            flag_specs.extend([
                ("institution", "기관 수급", False),
                ("foreign", "외국인 수급", False),
                ("individual", "개인 수급", False),
            ])
        for key, title, default in flag_specs:
            box = QCheckBox(title)
            box.setChecked(default)
            box.toggled.connect(self.redrawRequested.emit)
            self.flags[key] = box
            row.addWidget(box)
        row.addStretch(1)

    def _full_period(self) -> None:
        self.days.setValue(0)
        self.redrawRequested.emit()

    def days_value(self) -> int | None:
        return self.days.value() or None

    def options(self) -> ChartDisplayOptions:
        checked = lambda key: bool(self.flags.get(key) and self.flags[key].isChecked())
        return ChartDisplayOptions(
            timeframe=str(self.timeframe.currentData() or "D"),
            show_volume=checked("volume"),
            show_rsi=checked("rsi"),
            show_macd=checked("macd"),
            show_stochastic=checked("stochastic"),
            show_institution=checked("institution"),
            show_foreign=checked("foreign"),
            show_individual=checked("individual"),
        )


class ClassicStrategyPanel(QGroupBox):
    """Reusable strategy selector/presentation without calculation logic."""

    def __init__(self, parent=None):
        super().__init__("차트 고전전략 판정", parent)
        self._assessments = ()
        row = QHBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItems(STRATEGY_OPTIONS)
        self.mode.currentTextChanged.connect(self._refresh)
        self.text = QLabel("차트 자료를 불러온 뒤 자동으로 판정합니다.")
        self.text.setWordWrap(True)
        row.addWidget(self.mode)
        row.addWidget(self.text, 1)

    def set_assessments(self, assessments) -> None:
        self._assessments = tuple(assessments or ())
        self._refresh()

    def _refresh(self, *_args) -> None:
        if not self._assessments:
            self.text.setText("고전전략 판정 자료가 부족하거나 아직 차트를 불러오는 중입니다.")
            return
        try:
            value = format_strategy_assessments(self._assessments, self.mode.currentText() or ALL_STRATEGIES)
            self.text.setText(value + "\n※ 저장된 가격자료에 대한 규칙 기반 참고 판정입니다.")
        except Exception as exc:
            self.text.setText(str(exc))
