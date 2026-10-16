import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from krx_research.qt.job_menu.window import KrxJobMenuWindow
from krx_research.qt.pattern_search.window import PatternSearchDialog


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
            dialog.close()


if __name__ == "__main__":
    unittest.main()
