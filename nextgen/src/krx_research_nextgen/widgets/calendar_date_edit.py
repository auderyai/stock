from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDateEdit, QWidget


class CalendarDateEdit(QDateEdit):
    """ISO date editor with a visible calendar and bounded selectable dates."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.calendarWidget().setGridVisible(True)
        self.setEnabled(False)

    def set_bounds(self, earliest: date, latest: date) -> None:
        self.setDateRange(self._qdate(earliest), self._qdate(latest))
        self.setDate(self._qdate(latest))
        self.setEnabled(True)

    def value(self) -> date:
        return self.date().toPyDate()

    @staticmethod
    def _qdate(value: date) -> QDate:
        return QDate(value.year, value.month, value.day)
