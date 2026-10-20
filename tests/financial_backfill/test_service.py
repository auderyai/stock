from pathlib import Path
import unittest
from unittest.mock import MagicMock

from krx_research.financial_backfill.models import FinancialPeriod
from krx_research.financial_backfill.service import (
    FinancialBackfillContext,
    FinancialBackfillService,
)


class FinancialBackfillServiceTests(unittest.TestCase):
    def test_next_year_collection_does_not_wait_for_local_verification(self) -> None:
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
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=MagicMock()
        )
        service.cloud_collect = MagicMock(return_value={"status": "partial", "year": 2024})
        self.assertEqual(
            {"status": "partial", "year": 2024},
            service.cloud_collect_next(years=(2025, 2024, 2023)),
        )
        service.cloud_collect.assert_called_once_with(
            2024, years=(2025, 2024, 2023), batch_size=100, max_batches=0
        )

    def test_cloud_advances_after_completed_period_without_local_sync(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = {
            "format_version": 1,
            "year_order": [2025],
            "years": {"2025": {"periods": {"Q1": {"cloud_completed": True}}}},
        }
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=MagicMock()
        )
        service._collect_period = MagicMock(
            return_value={"status": "complete", "year": 2025, "period": "HALF"}
        )

        self.assertEqual(
            {"status": "complete", "year": 2025, "period": "HALF"},
            service.cloud_collect(2025, years=(2025,)),
        )
        self.assertIs(
            service._collect_period.call_args.args[2],
            FinancialPeriod.HALF,
        )

    def test_drive_retention_does_not_block_cloud_collection(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = {
            "format_version": 1,
            "year_order": [2025],
            "years": {"2025": {"periods": {"Q1": {
                "cloud_completed": True, "local_completed": True,
                "drive_cleaned": False,
            }}}},
        }
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=MagicMock()
        )
        service._collect_period = MagicMock(
            return_value={"status": "complete", "year": 2025, "period": "HALF"}
        )

        self.assertEqual(
            {"status": "complete", "year": 2025, "period": "HALF"},
            service.cloud_collect(2025, years=(2025,)),
        )

    def test_cloud_collection_requires_client(self) -> None:
        drive = MagicMock(root_folder_id="root")
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )
        with self.assertRaisesRegex(RuntimeError, "OpenDART 클라이언트"):
            service.cloud_collect(2025)

    def test_ready_sync_does_not_create_missing_cloud_state(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = None
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )

        self.assertEqual(
            {"status": "awaiting-cloud", "years": [2026, 2025, 2024, 2023]},
            service.sync_ready_local(),
        )
        drive.write_json.assert_not_called()

    def test_ready_sync_applies_only_first_complete_year(self) -> None:
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
        service.sync_local = MagicMock(return_value={"status": "complete", "year": 2025})

        self.assertEqual(
            {"status": "complete", "year": 2025},
            service.sync_ready_local(years=(2025, 2024, 2023)),
        )
        service.sync_local.assert_called_once_with(
            2025, years=(2025, 2024, 2023), cleanup_confirmed=False
        )

    def test_existing_history_checkpoint_is_extended_with_current_year(self) -> None:
        drive = MagicMock(root_folder_id="root")
        document = {
            "format_version": 1,
            "year_order": [2025, 2024, 2023],
            "years": {},
        }
        drive.read_json.return_value = document
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )

        self.assertEqual(
            [2026, 2025, 2024, 2023], service.status()["year_order"]
        )
        drive.write_json.assert_called_once()

    def test_ready_sync_revalidates_completed_year_until_drive_is_cleaned(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = {
            "format_version": 1,
            "year_order": [2025],
            "years": {"2025": {"local_completed": True, "drive_cleaned": False}},
        }
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )
        service.sync_local = MagicMock(return_value={"status": "complete", "year": 2025})

        self.assertEqual(
            {"status": "complete", "year": 2025},
            service.sync_ready_local(years=(2025,)),
        )
        service.sync_local.assert_called_once_with(
            2025, years=(2025,), cleanup_confirmed=False
        )


if __name__ == "__main__":
    unittest.main()
