from __future__ import annotations

import unittest

from krx_research.financial_backfill.models import FinancialPeriod
from krx_research.financial_backfill.staging import (
    DuckDbFinancialStagingRepository,
    FinancialStagingError,
)


class DuckDbFinancialStagingTests(unittest.TestCase):
    def test_current_and_cumulative_amounts_are_distinct_facts(self) -> None:
        rows = [{
            "rcept_no": "20260515000001", "corp_code": "00126380", "fs_div": "CFS",
            "sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
            "account_detail": "", "thstrm_amount": "1,000", "thstrm_add_amount": "2,500",
            "currency": "KRW", "ord": "1",
        }]
        facts = DuckDbFinancialStagingRepository().normalize(
            rows, year=2025, period=FinancialPeriod.HALF
        )
        self.assertEqual({"current", "current_cumulative"}, {fact["value_kind"] for fact in facts})
        self.assertEqual(2, len({fact["fact_key"] for fact in facts}))

    def test_exact_provider_duplicates_are_collapsed(self) -> None:
        row = self._row()
        facts = DuckDbFinancialStagingRepository().normalize(
            [row, dict(row)], year=2025, period=FinancialPeriod.Q1
        )
        self.assertEqual(1, len(facts))

    def test_repeated_account_lines_are_distinguished_by_ordinal(self) -> None:
        first = self._row()
        second = {**first, "ord": "2", "thstrm_amount": "2,000"}
        facts = DuckDbFinancialStagingRepository().normalize(
            [first, second], year=2025, period=FinancialPeriod.Q1
        )
        self.assertEqual(2, len(facts))
        self.assertEqual(2, len({fact["fact_key"] for fact in facts}))

    def test_conflicting_duplicate_fact_is_rejected(self) -> None:
        first = self._row()
        second = {**first, "thstrm_amount": "2,000"}
        with self.assertRaisesRegex(FinancialStagingError, "충돌=1"):
            DuckDbFinancialStagingRepository().normalize(
                [first, second], year=2025, period=FinancialPeriod.Q1
            )

    @staticmethod
    def _row() -> dict[str, str]:
        return {
            "rcept_no": "20260515000001", "corp_code": "00126380", "fs_div": "CFS",
            "sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
            "account_detail": "", "thstrm_amount": "1,000", "currency": "KRW", "ord": "1",
        }


if __name__ == "__main__":
    unittest.main()
