from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "stock_drive_sync_cli", ROOT / "scripts" / "stock_drive_sync.py"
)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class CloudCliTests(unittest.TestCase):
    def test_delayed_schedule_before_cutoff_uses_previous_day(self) -> None:
        now = datetime(2026, 10, 16, 7, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual("2026-10-15", CLI._default_target_date(now).isoformat())

    def test_schedule_after_cutoff_uses_current_day(self) -> None:
        now = datetime(2026, 10, 16, 20, 37, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual("2026-10-16", CLI._default_target_date(now).isoformat())


if __name__ == "__main__":
    unittest.main()
