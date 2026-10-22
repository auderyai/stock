from __future__ import annotations

import os
import unittest

import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from krx_research_nextgen.widgets.result_table import ResultTable
from krx_research_nextgen.windows.auxiliary_windows import _Table


class NextGenResultTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_numeric_sort_uses_ticker_as_stable_tie_breaker(self) -> None:
        table = ResultTable()
        table.set_frame(pd.DataFrame([
            {"stock_code": "005930", "score_value": 10},
            {"stock_code": "000660", "score_value": 10},
            {"stock_code": "035420", "score_value": 2},
        ]))

        table.model().sort(1, Qt.SortOrder.DescendingOrder)

        self.assertEqual([10, 10, 2], table.frame["score_value"].tolist())
        self.assertEqual(["000660", "005930", "035420"], table.frame["stock_code"].tolist())

    def test_navigation_uses_current_sorted_rows_and_formatted_codes(self) -> None:
        table = ResultTable()
        table.set_frame(pd.DataFrame([
            {"stock_code": 5930, "score_value": 2},
            {"stock_code": 660, "score_value": 10},
        ]), labels={"stock_code": "종목코드", "score_value": "점수"})
        table.model().sort(1, Qt.SortOrder.DescendingOrder)

        payload = table.navigation_payload("검증")

        self.assertIsNotNone(payload)
        self.assertEqual(["000660", "005930"], [item["code"] for item in payload["items"]])
        self.assertEqual(("종목코드", "점수"), payload["headers"])

    def test_formatted_numeric_text_still_sorts_numerically(self) -> None:
        table = ResultTable()
        table.set_frame(pd.DataFrame([
            {"stock_code": "005930", "return_pct": "9.5%"},
            {"stock_code": "000660", "return_pct": "10.0%"},
            {"stock_code": "035420", "return_pct": "1,200.0%"},
        ]))

        table.model().sort(1, Qt.SortOrder.DescendingOrder)

        self.assertEqual(
            ["1,200.0%", "10.0%", "9.5%"],
            table.frame["return_pct"].tolist(),
        )

    def test_index_code_is_not_padded_as_a_stock_ticker(self) -> None:
        table = ResultTable(identity_columns=("index_code",), identity_width=0)
        table.set_frame(pd.DataFrame([{"index_code": "001", "index_name": "코스피"}]))

        displayed = table.model().index(0, 0).data(Qt.ItemDataRole.DisplayRole)

        self.assertEqual("001", displayed)
        self.assertEqual("001", table.current_ticker())

    def test_new_ranked_results_reset_to_rank_then_ticker_order(self) -> None:
        table = ResultTable()
        table.set_frame(pd.DataFrame([
            {"rank": 2, "stock_code": "005930", "score_value": 99},
            {"rank": 1, "stock_code": "035420", "score_value": 10},
            {"rank": 1, "stock_code": "000660", "score_value": 10},
        ]))

        self.assertEqual([1, 1, 2], table.frame["rank"].tolist())
        self.assertEqual(["000660", "035420", "005930"], table.frame["stock_code"].tolist())

        table.model().sort(2, Qt.SortOrder.DescendingOrder)
        table.set_frame(pd.DataFrame([
            {"rank": 2, "stock_code": "005930", "score_value": 99},
            {"rank": 1, "stock_code": "000660", "score_value": 10},
        ]))

        self.assertEqual([1, 2], table.frame["rank"].tolist())

    def test_stock_code_is_center_aligned(self) -> None:
        table = ResultTable()
        table.set_frame(pd.DataFrame([{"stock_code": "002360", "stock_name": "SH에너지화학"}]))

        alignment = table.model().index(0, 0).data(Qt.ItemDataRole.TextAlignmentRole)

        self.assertEqual(Qt.AlignmentFlag.AlignCenter, alignment)

    def test_chart_navigation_preserves_source_alignment(self) -> None:
        table = ResultTable()
        table.set_frame(
            pd.DataFrame([{"value_0": "002360"}]),
            alignment_overrides={"value_0": "center"},
        )

        alignment = table.model().index(0, 0).data(Qt.ItemDataRole.TextAlignmentRole)

        self.assertEqual(Qt.AlignmentFlag.AlignCenter, alignment)

    def test_auxiliary_code_column_is_center_aligned(self) -> None:
        table = _Table(("시장", "코드", "종합·업종 지수"), identity_key="index_code")
        table.fill(
            [{"index_code": "L313", "market": "KOSDAQ", "name": "IT 서비스"}],
            lambda row: (row["market"], row["index_code"], row["name"]),
        )

        alignment = table.model().index(0, 2).data(Qt.ItemDataRole.TextAlignmentRole)

        self.assertEqual(Qt.AlignmentFlag.AlignCenter, alignment)


if __name__ == "__main__":
    unittest.main()
