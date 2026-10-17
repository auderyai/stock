from pathlib import Path
import unittest
from unittest.mock import MagicMock

from krx_research.financial_backfill.service import (
    FinancialBackfillContext,
    FinancialBackfillService,
)


class FinancialBackfillServiceTests(unittest.TestCase):
    def test_next_year_waits_for_current_year_local_verification(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = {
            "format_version": 1,
            "year_order": [2025, 2024, 2023],
            "years": {
                "2025": {
                    "periods": {
                        name: {"cloud_completed": True}
                        for name in ("Q1", "HALF", "Q3", "ANNUAL")
                    }
                }
            },
        }
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )
        self.assertEqual(
            {"status": "awaiting-local", "year": 2025},
            service.cloud_collect_next(),
        )

    def test_cloud_collection_requires_client(self) -> None:
        drive = MagicMock(root_folder_id="root")
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )
        with self.assertRaisesRegex(RuntimeError, "OpenDART 클라이언트"):
            service.cloud_collect(2025)


if __name__ == "__main__":
    unittest.main()
