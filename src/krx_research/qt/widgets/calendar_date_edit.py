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

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(
            QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self
        ).center()
        position = QPointF(arrow)
        popup_event = QMouseEvent(
            QEvent.MouseButtonPress, position, self.mapToGlobal(arrow),
            Qt.LeftButton, Qt.LeftButton, event.modifiers(),
        )
        super().mousePressEvent(popup_event)
