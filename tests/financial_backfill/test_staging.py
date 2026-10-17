from __future__ import annotations

import unittest

from krx_research.financial_backfill.models import FinancialPeriod
from krx_research.financial_backfill.staging import DuckDbFinancialStagingRepository


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


if __name__ == "__main__":
    unittest.main()
