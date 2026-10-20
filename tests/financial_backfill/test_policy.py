from __future__ import annotations

from datetime import date
import unittest

from krx_research.financial_backfill.models import FinancialPeriod
from krx_research.financial_backfill.policy import FinancialBackfillPolicy


class FinancialBackfillPolicyTests(unittest.TestCase):
    def test_period_order_is_quarter_half_third_quarter_annual(self) -> None:
        self.assertEqual(
            ["Q1", "HALF", "Q3", "ANNUAL"],
            [period.label for period in FinancialBackfillPolicy.PERIODS],
        )

    def test_next_period_skips_only_cloud_completed_periods(self) -> None:
        state = {"periods": {"Q1": {"cloud_completed": True}}}
        self.assertIs(FinancialPeriod.HALF, FinancialBackfillPolicy.next_period(state))

    def test_current_year_exposes_only_conservatively_available_periods(self) -> None:
        self.assertEqual(
            (FinancialPeriod.Q1, FinancialPeriod.HALF),
            FinancialBackfillPolicy.available_periods(
                2026, today=date(2026, 10, 18)
            ),
        )

    def test_future_year_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FinancialBackfillPolicy.validate_year(2027, today=date(2026, 10, 18))

    def test_year_order_can_only_be_extended_at_the_front(self) -> None:
        self.assertEqual(
            [2026, 2025, 2024, 2023],
            FinancialBackfillPolicy.extend_year_order(
                [2025, 2024, 2023], [2026, 2025, 2024, 2023]
            ),
        )
        with self.assertRaises(RuntimeError):
            FinancialBackfillPolicy.extend_year_order(
                [2025, 2024, 2023], [2025, 2023]
            )


if __name__ == "__main__":
    unittest.main()
