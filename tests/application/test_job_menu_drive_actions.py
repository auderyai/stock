from __future__ import annotations

import datetime as dt
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from krx_research.application.job_menu.models import JobKind, JobRequest
from krx_research.application.job_menu.service import JobMenuApplicationService
from krx_research.infrastructure.job_menu import PythonJobExecutor


class JobMenuDriveActionTests(unittest.TestCase):
    def test_drive_actions_delegate_to_stock_drive_entrypoint(self) -> None:
        executor = PythonJobExecutor(Path.cwd())
        verify = executor._build_command(JobRequest(JobKind.DRIVE_VERIFY))
        update = executor._build_command(JobRequest(JobKind.DRIVE_UPDATE))
        cleanup = executor._build_command(JobRequest(
            JobKind.DRIVE_CLEANUP, end=dt.date(2026, 10, 13)
        ))

        self.assertEqual("verify", verify[-1])
        self.assertEqual("update-local", update[-1])
        self.assertIn("cleanup-synced", cleanup)
        self.assertIn("2026-10-13", cleanup)
        self.assertEqual("DELETE_SYNCED_DRIVE_DELTAS", cleanup[-1])

    def test_cleanup_requires_reference_date(self) -> None:
        service = JobMenuApplicationService(MagicMock())
        with self.assertRaisesRegex(ValueError, "정리 기준일"):
            service.run(JobRequest(JobKind.DRIVE_CLEANUP))


if __name__ == "__main__":
    unittest.main()
