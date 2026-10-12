from __future__ import annotations

import argparse
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from krx_research.data_engine import cli


class DataEngineCliUpdateTests(unittest.TestCase):
    def test_update_initializes_core_schema_before_writing_run_history(self) -> None:
        target = date(2026, 10, 8)
        repository = MagicMock()
        repository.__enter__.return_value = repository
        repository.settings.provider_delay_seconds = 0
        repository.latest_ohlcv_date.return_value = target
        result = SimpleNamespace(
            target_date=target,
            ohlcv_rows=1,
            investor_rows=0,
            markets_completed=("KOSPI", "KOSDAQ"),
            skipped=False,
            messages=(),
            metadata={"status": "completed"},
        )
        updater = MagicMock()
        updater.update_date.return_value = result
        args = argparse.Namespace(
            as_of=target,
            markets=("KOSPI", "KOSDAQ"),
            no_investor=True,
            force=False,
        )

        with patch.object(cli, "_repository", return_value=repository), patch.object(
            cli, "PykrxBaseProvider"
        ), patch.object(cli, "IncrementalBaseUpdater", return_value=updater):
            code = cli.command_update(args)

        self.assertEqual(0, code)
        repository.initialize_schema.assert_called_once_with()
        updater.update_date.assert_called_once()


if __name__ == "__main__":
    unittest.main()
