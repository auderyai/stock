from __future__ import annotations

import os
from datetime import date
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.cloud_sync.service import (
    CloudArchiveError,
    StockDriveSyncService,
    SyncContext,
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

        with patch.object(service, "_run", side_effect=[3, 3, 0]) as run:
            result = service._run_menu2_with_retry("2026-10-12")

        self.assertEqual(0, result)
        self.assertEqual(3, run.call_count)
        self.assertEqual((0, 2, 3), run.call_args_list[0].kwargs["accepted"])
        self.assertEqual((0, 2, 3), run.call_args_list[1].kwargs["accepted"])
        self.assertEqual((0, 2), run.call_args_list[2].kwargs["accepted"])

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

    def test_failed_menu5_batch_is_saved_without_advancing_offset(self) -> None:
        root = Path.cwd()
        credentials = DriveCredentials("id", "secret", "refresh", "folder", "key")
        service = StockDriveSyncService(SyncContext(root, credentials))
        metadata = {"delta_folder_id": "deltas", "menu5_next_offset": 300}

        with patch.object(service, "_run", return_value=3), patch.object(
            service, "_publish_recovery_checkpoint",
            return_value=(metadata, {"stage": "menu5-partial"}),
        ) as partial:
            with self.assertRaisesRegex(CloudArchiveError, "다음 재개 위치=300"):
                service._run_menu5_checkpointed(
                    object(), metadata, root, "db", date(2026, 10, 12), "abcdef123456"
                )

        self.assertEqual(300, partial.call_args.kwargs["next_offset"])

    def test_next_date_waits_until_previous_menu7_checkpoint(self) -> None:
        with self.assertRaisesRegex(CloudArchiveError, "이전 기준일 작업이 완료되지 않아"):
            StockDriveSyncService._require_previous_date_completed(
                date(2026, 10, 12), date(2026, 10, 13), "menu5", "menu2"
            )

    def test_next_date_starts_after_previous_menu7_checkpoint(self) -> None:
        StockDriveSyncService._require_previous_date_completed(
            date(2026, 10, 12), date(2026, 10, 13), "menu7", "menu2"
        )


if __name__ == "__main__":
    unittest.main()
