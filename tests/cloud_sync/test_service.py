from __future__ import annotations

import os
from datetime import date
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.cloud_sync.service import (
    CloudArchiveError,
    StockDriveSyncService,
    SyncContext,
    TransientSourceError,
)


class CloudSyncServiceTests(unittest.TestCase):
    def test_child_script_receives_project_src_on_pythonpath(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))

        with patch.dict(os.environ, {"PYTHONPATH": "existing-path"}), patch(
            "krx_research.cloud_sync.service.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run:
            service._run("scripts/example.py")

        env = run.call_args.kwargs["env"]
        self.assertEqual(
            [str(root / "src"), "existing-path"],
            env["PYTHONPATH"].split(os.pathsep),
        )

    def test_cloud_menu7_retries_once_after_partial_completion(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))

        with patch.object(service, "_run", side_effect=[3, 0]) as run:
            service._run_menu7_with_retry("2026-10-12")

        self.assertEqual(2, run.call_count)
        self.assertEqual((0, 3), run.call_args_list[0].kwargs["accepted"])
        self.assertNotIn("accepted", run.call_args_list[1].kwargs)

    def test_cloud_menu2_retries_transient_provider_failures(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))

        with patch.object(service, "_run", side_effect=[3, 3]) as run:
            result = service._run_menu2_with_retry("2026-10-12")

        self.assertEqual(3, result)
        self.assertEqual(2, run.call_count)
        self.assertEqual((0, 2, 3), run.call_args_list[0].kwargs["accepted"])
        self.assertEqual((0, 2, 3), run.call_args_list[1].kwargs["accepted"])

    def test_cloud_menu2_returns_confirmed_holiday_without_retry(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))

        with patch.object(service, "_run", return_value=2) as run:
            result = service._run_menu2_with_retry("2026-10-09")

        self.assertEqual(2, result)
        run.assert_called_once()

    def test_existing_target_date_continues_to_later_menus(self) -> None:
        target = date(2026, 10, 12)

        result = StockDriveSyncService._validate_menu2_date(
            target, target, target, 0
        )

        self.assertIsNone(result)

    def test_confirmed_holiday_returns_no_new_status(self) -> None:
        before = date(2026, 10, 8)
        target = date(2026, 10, 9)

        result = StockDriveSyncService._validate_menu2_date(
            before, before, target, 2
        )

        self.assertEqual(
            {"status": "no-new-trading-day", "requested_date": "2026-10-09"},
            result,
        )

    def test_provider_failure_is_reported_without_discarding_checkpoints(self) -> None:
        before = date(2026, 10, 12)
        result = StockDriveSyncService._validate_menu2_date(
            before, before, date(2026, 10, 13), 3
        )
        self.assertEqual(
            {"status": "provider-failed", "requested_date": "2026-10-13"},
            result,
        )

    def test_public_result_reports_latest_persisted_stage(self) -> None:
        result = StockDriveSyncService._public_result(
            {
                "state": {"reference_date": "2026-10-12"},
                "deltas": [{"reference_date": "2026-10-12"}],
                "completed_stage": "menu5",
            }
        )

        self.assertEqual("menu5", result["completed_stage"])

    def test_later_stage_requires_exact_menu2_reference_date(self) -> None:
        with self.assertRaisesRegex(Exception, "기준일이 준비되지 않았습니다"):
            StockDriveSyncService._require_reference_date(
                date(2026, 10, 8), date(2026, 10, 12), "menu5"
            )

    def test_later_stage_accepts_exact_menu2_reference_date(self) -> None:
        StockDriveSyncService._require_reference_date(
            date(2026, 10, 12), date(2026, 10, 12), "menu7"
        )

    def test_completed_menu_is_not_run_again(self) -> None:
        self.assertTrue(StockDriveSyncService._stage_completed("menu5", "menu5"))
        self.assertTrue(StockDriveSyncService._stage_completed("menu7", "menu5"))
        self.assertFalse(StockDriveSyncService._stage_completed("menu2", "menu5"))
        self.assertFalse(StockDriveSyncService._stage_completed("menu5-partial", "menu5"))

    def test_menu5_batches_checkpoint_and_finish(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))
        metadata = {"delta_folder_id": "deltas"}

        with patch.object(service, "_run", side_effect=[0, 0, 4]) as run, patch.object(
            service, "_publish_recovery_checkpoint",
            side_effect=[
                ({**metadata, "menu5_next_offset": 100}, {"stage": "menu5-partial"}),
                ({**metadata, "menu5_next_offset": 200}, {"stage": "menu5-partial"}),
            ],
        ) as partial, patch.object(
            service, "_publish_checkpoint",
            return_value=({**metadata, "completed_stage": "menu5"}, {"stage": "menu5"}),
        ) as final:
            result_metadata, checkpoints = service._run_menu5_checkpointed(
                object(), metadata, root, "db", date(2026, 10, 12), "abcdef123456"
            )

        self.assertEqual(3, run.call_count)
        self.assertEqual(2, partial.call_count)
        self.assertEqual(1, final.call_count)
        self.assertEqual("menu5", result_metadata["completed_stage"])
        self.assertEqual(["menu5-partial", "menu5-partial", "menu5"], [c["stage"] for c in checkpoints])

    def test_cloud_menu5_returns_final_checkpoint_rows(self) -> None:
        target = date(2026, 10, 12)
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))
        drive = MagicMock()
        drive.__enter__.return_value = drive
        connection = MagicMock()
        connection.__enter__.return_value = MagicMock()
        metadata = {
            "state": {"id": "state", "name": "state.enc"},
            "completed_stage": "menu2",
        }
        completed = {**metadata, "completed_stage": "menu5"}

        with patch.object(SyncContext, "drive", return_value=drive), patch.object(
            service, "_metadata", return_value=metadata
        ), patch.object(service, "_verify_download"), patch(
            "krx_research.cloud_sync.service.ArchiveCipher.decrypt"
        ), patch(
            "krx_research.cloud_sync.service.DatabaseArchiveService"
        ), patch.object(
            service, "_connection", return_value=connection
        ), patch.object(
            service, "_apply_cloud_deltas"
        ), patch.object(
            service, "_latest_date", return_value=target
        ), patch.object(
            service, "_git_commit", return_value="abcdef123456"
        ), patch.object(
            service,
            "_run_menu5_checkpointed",
            return_value=(completed, [{"stage": "menu5", "delta_rows": 7}]),
        ):
            result = service.cloud_run(target, stage="menu5")

        self.assertEqual("menu5", result["completed_stage"])
        self.assertEqual(7, result["delta_rows"])

    def test_failed_menu5_batch_is_saved_without_advancing_offset(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))
        metadata = {"delta_folder_id": "deltas", "menu5_next_offset": 300}

        with patch.object(service, "_run", side_effect=[3, 3]), patch.object(
            service, "_publish_recovery_checkpoint",
            return_value=(metadata, {"stage": "menu5-partial"}),
        ) as partial:
            with self.assertRaisesRegex(TransientSourceError, "재개 위치=300"):
                service._run_menu5_checkpointed(
                    object(), metadata, root, "db", date(2026, 10, 12), "abcdef123456"
                )

        self.assertEqual(300, partial.call_args.kwargs["next_offset"])
        self.assertEqual(2, partial.call_count)

    def test_next_date_waits_until_previous_menu7_checkpoint(self) -> None:
        with self.assertRaisesRegex(CloudArchiveError, "이전 기준일 작업이 완료되지 않아"):
            StockDriveSyncService._require_previous_date_completed(
                date(2026, 10, 12), date(2026, 10, 13), "menu5", "menu2"
            )

    def test_next_date_starts_after_previous_menu7_checkpoint(self) -> None:
        StockDriveSyncService._require_previous_date_completed(
            date(2026, 10, 12), date(2026, 10, 13), "menu7", "menu2"
        )

    def test_cleanup_deletes_only_locally_applied_deltas_older_than_30_days(self) -> None:
        root = Path.cwd()
        service = StockDriveSyncService(SyncContext(
            root, DriveCredentials("id", "secret", "refresh", "folder", "key")
        ))
        drive = MagicMock(root_folder_id="folder")
        metadata = {
            "delta_folder_id": "deltas",
            "deltas": [
                {"id": "old", "reference_date": "2026-09-01"},
                {"id": "kept", "reference_date": "2026-10-01"},
            ]
        }
        drive.list_folder.return_value = [
            {"id": "orphan", "name": "delta-2026-09-02-menu5-old.enc"},
            {"id": "recent", "name": "delta-2026-10-01-menu7-new.enc"},
        ]

        with patch.object(service, "_retention_cutoff", return_value=date(2026, 9, 15)):
            cleaned = service._acknowledge_and_cleanup(drive, metadata)

        self.assertEqual(["2026-09-01"], cleaned)
        self.assertEqual({"old", "orphan"}, {call.args[0] for call in drive.delete.call_args_list})
        self.assertEqual("2026-10-01", metadata["local_synced_through"])
        self.assertEqual(["kept"], [item["id"] for item in metadata["deltas"]])


if __name__ == "__main__":
    unittest.main()
