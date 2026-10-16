from __future__ import annotations

import re

from PySide6.QtCore import QObject, QStringListModel, QTimer, Qt, Signal
from PySide6.QtWidgets import QCompleter, QLineEdit


class SecurityCompleter(QObject):
    """Reusable delayed stock-name/code completer for every ticker input."""

    searchRequested = Signal(str)

    def __init__(self, editor: QLineEdit, parent=None):
        super().__init__(parent or editor)
        self.editor, self._codes = editor, {}
        self.model = QStringListModel(self)
        self.completer = QCompleter(self.model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        editor.setCompleter(self.completer)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(250)
        editor.textEdited.connect(lambda _text: self.timer.start())
        self.timer.timeout.connect(self._request)
        self.completer.activated[str].connect(self._select)

    def set_matches(self, rows: list[dict[str, str]]) -> None:
        self._codes = {
            f"{str(row.get('ticker', '')).zfill(6)}  {row.get('name', '')}  [{row.get('market', '')}]":
            str(row.get("ticker", "")).zfill(6)
            for row in rows
        }
        self.model.setStringList(list(self._codes))
        if self._codes and self.editor.hasFocus():
            self.completer.complete()

    def _request(self) -> None:
        query = self.editor.text().strip()
        if query:
            self.searchRequested.emit(query)
        else:
            self.set_matches([])

    def _select(self, label: str) -> None:
        if code := self._codes.get(label):
            self.editor.setText(code)

    @staticmethod
    def value(text: str) -> str:
        """Return a ticker from a selected label, or the untouched search text."""
        value = text.strip()
        match = re.match(r"^(\d{6})(?:\b|\s)", value)
        return match.group(1) if match else value
