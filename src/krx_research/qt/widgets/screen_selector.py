from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget

from krx_research.policies.workstation_options import SCREEN_TITLES


class ScreenSelector(QListWidget):
    executeRequested = Signal()
    selectedKeyChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys = [key for key in SCREEN_TITLES if key != "near_high_52w"]
        for key in self._keys:
            self.addItem(SCREEN_TITLES[key])
        self.itemDoubleClicked.connect(lambda _item: self.executeRequested.emit())
        self.currentRowChanged.connect(self._emit_key)

    def _emit_key(self, row: int) -> None:
        if 0 <= row < len(self._keys):
            self.selectedKeyChanged.emit(self._keys[row])

    def selected_key(self) -> str | None:
        row = self.currentRow()
        return self._keys[row] if 0 <= row < len(self._keys) else None
