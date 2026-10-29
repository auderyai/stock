from __future__ import annotations

import unittest

from krx_research_nextgen.models.screening import ScreeningResult
from krx_research_nextgen.presentation.screening_table import LABELS, result_frame


class ScreeningTablePresentationTests(unittest.TestCase):
    def test_52week_screen_exposes_search_value(self) -> None:
        row = ScreeningResult(
            "005930", "삼성전자", "KOSPI", "2026-10-29", 99_000,
            high_52w=100_000, distance_from_high_pct=-1.0,
        )

        frame = result_frame([row])

        self.assertEqual(
            ["high_52w", "distance_from_high_pct"],
            list(frame.columns[-2:]),
        )
        self.assertEqual("52주 최고가 대비 종가(%)", LABELS["distance_from_high_pct"])

    def test_other_screens_do_not_gain_empty_52week_columns(self) -> None:
        row = ScreeningResult("005930", "삼성전자", "KOSPI", "2026-10-29", 99_000)
        self.assertNotIn("high_52w", result_frame([row]).columns)


if __name__ == "__main__":
    unittest.main()
