from __future__ import annotations

import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from krx_research_nextgen.widgets.calendar_date_edit import CalendarDateEdit


class CalendarDateEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_shows_calendar_and_enforces_database_bounds(self) -> None:
        editor = CalendarDateEdit()
        editor.set_bounds(date(2026, 1, 2), date(2026, 10, 16))

        self.assertTrue(editor.calendarPopup())
        self.assertTrue(editor.calendarWidget().isGridVisible())
        self.assertEqual(editor.displayFormat(), "yyyy-MM-dd")
        self.assertEqual(editor.minimumDate().toPyDate(), date(2026, 1, 2))
        self.assertEqual(editor.maximumDate().toPyDate(), date(2026, 10, 16))
        self.assertEqual(editor.value(), date(2026, 10, 16))
        self.assertTrue(editor.isEnabled())
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
