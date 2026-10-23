from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

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

    def test_restore_request_is_limited_to_explicit_deleted_periods(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = {
            "format_version": 1,
            "year_order": [2024, 2023],
            "years": {
                "2024": {"periods": {"Q3": {"drive_cleaned": True}}},
                "2023": {"periods": {"Q1": {"drive_cleaned": True}}},
            },
        }
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=MagicMock()
        )

        result = service.request_drive_restore(
            ((2024, FinancialPeriod.Q3), (2023, FinancialPeriod.Q1)),
            years=(2024, 2023),
        )

        self.assertEqual(
            {"status": "restore-requested", "periods": ["2024:Q3", "2023:Q1"]},
            result,
        )
        saved = drive.write_json.call_args.args[0]
        self.assertTrue(saved["restore_deleted_requested"])
        self.assertEqual(["2024:Q3", "2023:Q1"], saved["restore_deleted_targets"])

    def test_cloud_collection_prioritizes_requested_restore(self) -> None:
        drive = MagicMock(root_folder_id="root")
        drive.read_json.return_value = {
            "format_version": 1,
            "year_order": [2024],
            "restore_deleted_requested": True,
            "restore_deleted_targets": ["2024:Q3"],
            "years": {},
        }
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=MagicMock()
        )
        service._restore_next_deleted = MagicMock(
            return_value={"status": "complete", "restore_deleted": True}
        )

        result = service.cloud_collect_next(years=(2024,), batch_size=100)

        self.assertTrue(result["restore_deleted"])
        service._restore_next_deleted.assert_called_once()

    @patch("krx_research.financial_backfill.service.ArchiveCipher.decrypt")
    @patch("krx_research.financial_backfill.service.open_financial_repository")
    def test_local_sync_uses_local_database_not_shared_applied_flag(
        self, open_repository, decrypt
    ) -> None:
        drive = MagicMock(root_folder_id="root")
        metadata = {
            "format_version": 1,
            "year_order": [2024],
            "years": {"2024": {
                "target_periods": ["Q3"],
                "periods": {"Q3": {
                    "cloud_completed": True,
                    "facts": 1,
                    "batches": [{
                        "id": "drive-id", "name": "batch.enc", "sha256": "hash",
                        "batch_id": "batch", "local_applied": True,
                    }],
                }},
            }},
        }
        drive.read_json.return_value = metadata
        drive.download.side_effect = lambda _id, path: path
        repository = open_repository.return_value.__enter__.return_value
        repository.period_fact_count.side_effect = (0, 1)
        repository.apply_archive.return_value = {"batch_id": "batch"}
        service = FinancialBackfillService(
            FinancialBackfillContext(Path.cwd(), drive, "key"), client=None
        )
        service._sha256 = MagicMock(return_value="hash")

        result = service.sync_local(2024, years=(2024,))

        self.assertEqual("complete-period", result["status"])
        drive.download.assert_called_once()
        decrypt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
