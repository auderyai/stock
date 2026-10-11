from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from krx_research_nextgen.models.screening import ScreeningKind


class ScreeningPanel(QWidget):
    """Final Stage-4 screening control panel.

    One shared universe/TOP-N rule is used by every screener.
    Any criteria change emits reset_requested so stale results cannot remain.
    """

    run_requested = pyqtSignal(object, int, str)
    reset_requested = pyqtSignal()
    criteria_changed = pyqtSignal(object, int, str)

    UNIVERSES = (
        ("전체", "ALL"),
        ("KOSPI", "KOSPI"),
        ("KOSDAQ", "KOSDAQ"),
        ("KONEX", "KONEX"),
        ("KOSPI200", "KOSPI200"),
        ("KOSDAQ150", "KOSDAQ150"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()

        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("screeningKindCombo")
        for kind in ScreeningKind:
            self.kind_combo.addItem(kind.value, kind)

        self.market_combo = QComboBox()
        self.market_combo.setObjectName("screeningUniverseCombo")
        self.market_combo.setMinimumWidth(125)
        for label, value in self.UNIVERSES:
            self.market_combo.addItem(label, value)

        self.limit_spin = QSpinBox()
        self.limit_spin.setObjectName("screeningTopNSpin")
        self.limit_spin.setRange(1, 500)
        self.limit_spin.setSingleStep(10)
        self.limit_spin.setValue(50)
        self.limit_spin.setSuffix(" 종목")
        self.limit_spin.setMinimumWidth(105)

        self.run_button = QPushButton("TOP-N 실행")
        self.run_button.setObjectName("screeningRunButton")

        self.status_label = QLabel("대상: 전체 / TOP-50")
        self.status_label.setObjectName("screeningCriteriaStatus")

        row.addWidget(QLabel("스크리너"))
        row.addWidget(self.kind_combo, 1)
        row.addWidget(QLabel("대상"))
        row.addWidget(self.market_combo)
        row.addWidget(QLabel("TOP-N"))
        row.addWidget(self.limit_spin)
        row.addWidget(self.run_button)

        layout.addLayout(row)
        layout.addWidget(self.status_label)

        self.run_button.clicked.connect(self._emit_run)
        self.kind_combo.currentIndexChanged.connect(self._criteria_changed)
        self.market_combo.currentIndexChanged.connect(self._criteria_changed)
        self.limit_spin.valueChanged.connect(self._criteria_changed)

    def current_criteria(self) -> tuple[ScreeningKind, int, str]:
        return (
            self.kind_combo.currentData(),
            int(self.limit_spin.value()),
            str(self.market_combo.currentData()),
        )

    def _criteria_changed(self, *_args) -> None:
        kind, limit, universe = self.current_criteria()
        label = self.market_combo.currentText()
        self.status_label.setText(f"대상: {label} / TOP-{limit}")
        self.reset_requested.emit()
        self.criteria_changed.emit(kind, limit, universe)

    def _emit_run(self) -> None:
        kind, limit, universe = self.current_criteria()
        self.run_requested.emit(kind, limit, universe)
