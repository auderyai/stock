from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QWidget

from krx_research.qt.models.rank_limit import RankLimit


class RankLimitControl(QWidget):
    """Reusable compact Top-N input used by every ranked PySide6 view."""

    valueChanged = Signal(int)

    def __init__(self, value: int = 50, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("순위"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 5000)
        self.spin.setValue(int(value))
        self.spin.setSuffix(" 위")
        self.spin.valueChanged.connect(self.valueChanged)
        layout.addWidget(self.spin)

    def value(self) -> int:
        return RankLimit(self.spin.value()).validate().value

    def set_value(self, value: int) -> None:
        self.spin.setValue(RankLimit(value).validate().value)
