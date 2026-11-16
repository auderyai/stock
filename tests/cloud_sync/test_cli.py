from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from io import StringIO
import tempfile
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "stock_drive_sync_cli", ROOT / "scripts" / "stock_drive_sync.py"
)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class CloudCliTests(unittest.TestCase):
    def test_non_trading_day_has_distinct_exit_and_skip_audit(self):
        service = MagicMock()
        service.cloud_run.return_value = {'status': 'non-trading-day', 'reason': 'weekend'}
        with tempfile.TemporaryDirectory() as name, patch.object(CLI, 'ROOT', Path(name)), patch.object(
            CLI.DriveCredentials, 'from_environment'), patch.object(
            CLI, 'StockDriveSyncService', return_value=service), redirect_stdout(StringIO()):
            self.assertEqual(2, CLI.main(['cloud-run', '--date', '2026-11-15']))
            log = (Path(name)/'logs/cloud_sync/drive_sync.log').read_text(encoding='utf-8')
            self.assertIn('SKIPPED command=cloud-run', log)
            self.assertNotIn('SUCCESS', log)

    def test_delayed_schedule_before_cutoff_uses_previous_day(self) -> None:
        now = datetime(2026, 10, 16, 7, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual("2026-10-15", CLI._default_target_date(now).isoformat())

    def test_schedule_after_cutoff_uses_current_day(self) -> None:
        now = datetime(2026, 10, 16, 20, 37, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual("2026-10-16", CLI._default_target_date(now).isoformat())


if __name__ == "__main__":
    unittest.main()
