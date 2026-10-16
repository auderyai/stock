from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDateEdit, QStyle, QStyleOptionSpinBox


class CalendarDateEdit(QDateEdit):
    """Date editor whose whole field opens its calendar."""

    def __init__(self, date=None, parent=None):
        super().__init__(parent) if date is None else super().__init__(date, parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.calendarWidget().setGridVisible(True)
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self._open_calendar(event.modifiers())
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._open_calendar(event.modifiers())

    def _open_calendar(self, modifiers) -> None:
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(
            QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self
        ).center()
        position = QPointF(arrow)
        popup_event = QMouseEvent(
            QEvent.MouseButtonPress, position, self.mapToGlobal(arrow),
            Qt.LeftButton, Qt.LeftButton, modifiers,
        )
        super().mousePressEvent(popup_event)
