import unittest

import pandas as pd

from krx_research.qt.presentation.column_catalog import label_for
from krx_research_nextgen.presentation.ai_result_table import AiResultPresenter
from krx_research_nextgen.windows.stage4_main_window import Stage4MainWindow


class AiResultNavigationTests(unittest.TestCase):
    def test_ai_frame_becomes_chart_navigation_source(self):
        frame = pd.DataFrame([
            {"trading value rank within candidates": 1, "stock_code": "036930", "stock_name": "주성엔지니어링"},
            {"trading value rank within candidates": 2, "stock_code": "058470", "stock_name": "리노공업"},
        ])
        labels = {column: label_for(column) for column in frame.columns}
        presentation = AiResultPresenter().present(frame, labels)
        navigation = Stage4MainWindow._frame_navigation(presentation, "AI 분석 결과")
        self.assertEqual([item["code"] for item in navigation["items"]], ["036930", "058470"])
        self.assertEqual(navigation["title"], "AI 분석 결과")
        self.assertEqual(navigation["headers"][0], "후보 내 주간 거래대금 순위")

    def test_codes_dates_text_and_numbers_follow_table_rules(self):
        frame = pd.DataFrame([{"stock_code": 36930, "stock_name": "주성엔지니어링",
                               "as date": "2026-10-08", "weekly trading value": 333644100000}])
        labels = {column: label_for(column) for column in frame.columns}
        result = AiResultPresenter().present(frame, labels)
        self.assertEqual(result.alignments, ("center", "left", "center", "right"))
        self.assertEqual(result.rows[0], ("036930", "주성엔지니어링", "2026-10-08", "333,644,100,000"))

    def test_ai_english_field_names_have_korean_headers(self):
        expected = {
            "as date": "기준일",
            "wave1 start": "1파 시작일",
            "wave2 retracement pct": "2파 조정률(%)",
            "wave3 progress vs wave1": "추정 3파/1파 진행 배수",
            "volume 5d vs 20d": "5일/20일 평균 거래량 배수",
            "weekly trading value": "주간 거래대금(원)",
        }
        self.assertEqual({column: label_for(column) for column in expected}, expected)


if __name__ == "__main__":
    unittest.main()
