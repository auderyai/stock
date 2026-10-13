from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.cloud_sync.service import StockDriveSyncService, SyncContext


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


if __name__ == "__main__":
    unittest.main()
