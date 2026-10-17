from datetime import date
import unittest
from unittest.mock import MagicMock

from krx_research.qt.controllers.pattern_search_controller import PatternSearchController
from krx_research.qt.services.box_breakout import PeriodPatternQuery
from krx_research.qt.services.current_pattern import CurrentPatternKind, CurrentPatternQuery
from krx_research.qt.services.pattern_similarity import PatternSearchQuery


class PatternSearchControllerTests(unittest.TestCase):
    def setUp(self):
        self.similarity, self.period, self.current = MagicMock(), MagicMock(), MagicMock()
        self.controller = PatternSearchController(self.similarity, self.period, self.current)

    def test_routes_each_query_to_one_service(self):
        similarity_query = PatternSearchQuery("005930", date(2026, 1, 1), date(2026, 2, 1))
        period_query = PeriodPatternQuery("005930", date(2026, 1, 1), date(2026, 2, 1), 20)
        current_query = CurrentPatternQuery(CurrentPatternKind.DOUBLE_BOTTOM, 20)
        self.controller.command(similarity_query)()
        self.controller.command(period_query)()
        self.controller.command(current_query)()
        self.similarity.search.assert_called_once_with(similarity_query)
        self.period.search.assert_called_once_with(period_query)
        self.current.search.assert_called_once_with(current_query)

    def test_security_suggestions_are_delegated(self):
        self.similarity.suggest_securities.return_value = [{"ticker": "005930"}]
        self.assertEqual(self.controller.suggest_securities("삼성"), [{"ticker": "005930"}])


if __name__ == "__main__":
    unittest.main()
