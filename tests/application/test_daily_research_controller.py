from __future__ import annotations

from datetime import date
import unittest

from krx_research_nextgen.controllers.daily_research_controller import (
    DailyResearchController,
)


class _Service:
    def latest_date(self):
        return date(2026, 10, 16)

    def query(self, start, end):
        return ("query", start, end)

    def prepare_images(self, paths, report_date):
        return (tuple(paths), report_date)

    def commit_images(self, plan):
        return plan


class DailyResearchControllerTests(unittest.TestCase):
    def test_routes_operations_without_view_constructing_a_service(self) -> None:
        service = _Service()
        refresh = lambda start, end: ("refresh", start, end)
        repeated = lambda start, end: ("repeated", start, end)
        controller = DailyResearchController(
            service, refresh=refresh, repeated=repeated
        )
        start, end = date(2026, 10, 1), date(2026, 10, 16)

        self.assertEqual(controller.latest_date(), end)
        self.assertEqual(controller.query(start, end), ("query", start, end))
        self.assertEqual(controller.refresh(start, end), ("refresh", start, end))
        self.assertEqual(controller.repeated(start, end), ("repeated", start, end))

    def test_repeated_requires_an_explicit_feature_operation(self) -> None:
        controller = DailyResearchController(
            _Service(), refresh=lambda start, end: None
        )
        with self.assertRaisesRegex(ValueError, "특징주"):
            controller.repeated(date(2026, 10, 1), date(2026, 10, 16))


if __name__ == "__main__":
    unittest.main()
