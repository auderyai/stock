import unittest

import pandas as pd
from PySide6.QtCore import Qt

from krx_research.qt.common import DataFrameModel
from krx_research.qt.presentation.pattern_presenter import PatternResultPresenter


class PatternResultPresenterTests(unittest.TestCase):
    def test_similarity_order_is_score_desc_then_code_asc(self):
        rows = [
            {"stock_code": "2", "stock_name": "둘", "similarity_pct": 90},
            {"stock_code": "3", "stock_name": "셋", "similarity_pct": 95},
            {"stock_code": "1", "stock_name": "하나", "similarity_pct": 90},
        ]
        frame = PatternResultPresenter().present(rows)
        self.assertEqual(frame.columns[:4].tolist(),
                         ["rank", "stock_code", "stock_name", "similarity_pct"])
        self.assertEqual(frame.stock_code.tolist(), ["000003", "000001", "000002"])
        self.assertEqual(frame["rank"].tolist(), [1, 2, 3])

    def test_reference_pattern_is_first(self):
        rows = [
            {"pattern_role": "유사 패턴", "stock_code": "2", "stock_name": "둘", "similarity_pct": 99},
            {"pattern_role": "기준 패턴", "stock_code": "1", "stock_name": "하나", "similarity_pct": 100},
        ]
        frame = PatternResultPresenter().present(rows)
        self.assertEqual(frame.iloc[0].pattern_role, "기준 패턴")
        self.assertEqual(frame.iloc[0]["rank"], 0)

    def test_common_model_sorts_numbers_numerically(self):
        model = DataFrameModel(pd.DataFrame({"value": [2, 10, 1]}))
        model.sort(0, Qt.DescendingOrder)
        self.assertEqual(model.frame.value.tolist(), [10, 2, 1])

    def test_common_model_resets_rank_order_with_ticker_tie_breaker(self):
        model = DataFrameModel(pd.DataFrame([
            {"rank": 2, "stock_code": "005930"},
            {"rank": 1, "stock_code": "035420"},
            {"rank": 1, "stock_code": "000660"},
        ]))

        model.apply_default_sort()

        self.assertEqual(model.frame["rank"].tolist(), [1, 1, 2])
        self.assertEqual(model.frame["stock_code"].tolist(), ["000660", "035420", "005930"])

    def test_current_patterns_are_ranked_by_structure_score(self):
        rows = [
            {"stock_code": "2", "stock_name": "둘", "pattern_score": 80},
            {"stock_code": "1", "stock_name": "하나", "pattern_score": 90},
        ]
        frame = PatternResultPresenter().present(rows)
        self.assertEqual(frame.stock_code.tolist(), ["000001", "000002"])
        self.assertEqual(frame["rank"].tolist(), [1, 2])


if __name__ == "__main__":
    unittest.main()
