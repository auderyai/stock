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

    def test_previous_year_must_be_locally_completed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "2025년 로컬 검증 완료"):
            FinancialBackfillPolicy.require_previous_local_completion(
                [2025, 2024, 2023], {"years": {"2025": {}}}, 2024
            )

    def test_only_completed_years_are_allowed(self) -> None:
        with self.assertRaises(ValueError):
            FinancialBackfillPolicy.validate_year(2026, today=date(2026, 10, 18))


if __name__ == "__main__":
    unittest.main()
