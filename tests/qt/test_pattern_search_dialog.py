import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from krx_research.qt.job_menu.window import KrxJobMenuWindow, RangeDialog
from krx_research.qt.pattern_search.window import PatternSearchDialog
from krx_research.qt.widgets.security_completer import SecurityCompleter


class PatternSearchDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_job_menu_contains_pattern_search_as_number_three(self):
        with TemporaryDirectory() as directory:
            window = KrxJobMenuWindow(Path(directory))
            self.assertTrue(any(job.number == 3 for job in window._jobs))
            window.close()

    def test_result_chart_uses_existing_navigable_chart(self):
        with TemporaryDirectory() as directory:
            dialog = PatternSearchDialog(
                Path(directory), repository=MagicMock(), chart_service=MagicMock()
            )
            dialog._show_rows([
                {"stock_code": "078350", "stock_name": "한양디지텍", "similarity_pct": 80},
                {"stock_code": "000001", "stock_name": "상위종목", "similarity_pct": 95},
            ])
            self.assertEqual(dialog.table.frame.stock_code.tolist(), ["000001", "078350"])
            dialog.table.select_ticker("078350")
            with patch("krx_research.qt.pattern_search.window.ChartWindow") as chart:
                chart.return_value.destroyed.connect = MagicMock()
                dialog._open_chart()
            self.assertTrue(chart.call_args.kwargs["navigation_enabled"])
            self.assertEqual(chart.call_args.args[1], "078350")
            self.assertEqual(
                chart.call_args.kwargs["navigation_frame"].stock_code.tolist(),
                ["000001", "078350"],
            )
            dialog.close()

    def test_box_mode_keeps_reference_security_and_hides_manual_thresholds(self):
        with TemporaryDirectory() as directory:
            dialog = PatternSearchDialog(
                Path(directory), repository=MagicMock(), chart_service=MagicMock()
            )
            dialog.mode.setCurrentIndex(1)
            self.assertTrue(dialog.security.isEnabled())
            self.assertFalse(dialog.average.isEnabled())
            self.assertFalse(hasattr(dialog, "breakout"))
            self.assertIn("돌파 여부나 돌파일을 판단하지 않습니다", dialog.help.text())
            dialog.close()

    def test_partial_stock_name_offers_selectable_code(self):
        repository = MagicMock()
        repository.search_securities.return_value = [
            {"ticker": "078350", "name": "한양디지텍", "market": "KOSDAQ"}
        ]
        with TemporaryDirectory() as directory:
            dialog = PatternSearchDialog(
                Path(directory), repository=repository, chart_service=MagicMock()
            )
            dialog._suggest_security("한양")
            labels = dialog.security_completer.model.stringList()
            self.assertEqual(labels, ["078350  한양디지텍  [KOSDAQ]"])
            dialog.security_completer._select(labels[0])
            self.assertEqual(dialog.security.text(), "078350")
            dialog.close()

    def test_full_candidate_label_is_always_normalized_to_ticker(self):
        self.assertEqual(
            SecurityCompleter.value("098120  마이크로컨텍솔  [KOSDAQ]"),
            "098120",
        )

    def test_clicking_date_field_opens_calendar(self):
        with TemporaryDirectory() as directory:
            dialog = PatternSearchDialog(
                Path(directory), repository=MagicMock(), chart_service=MagicMock()
            )
            dialog.show()
            QTest.mouseClick(dialog.start, Qt.LeftButton, pos=dialog.start.rect().center())
            self.app.processEvents()
            self.assertTrue(dialog.start.calendarWidget().isVisible())
            dialog.start.calendarWidget().parentWidget().hide()
            dialog.close()

    def test_collection_range_dialog_reuses_partial_name_completer(self):
        search = MagicMock(return_value=[
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"}
        ])
        dialog = RangeDialog("수집", menu=5, security_search=search)
        dialog._suggest_security("삼성")
        label = dialog.ticker_completer.model.stringList()[0]
        dialog.ticker_completer._select(label)
        self.assertEqual(dialog.ticker.text(), "005930")
        search.assert_called_once_with("삼성", limit=20)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
