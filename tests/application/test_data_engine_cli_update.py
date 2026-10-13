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

    def test_provider_failure_is_not_reported_as_no_trading_day(self) -> None:
        target = date(2026, 10, 12)
        repository = MagicMock()
        repository.__enter__.return_value = repository
        repository.settings.provider_delay_seconds = 0
        repository.latest_ohlcv_date.return_value = date(2026, 10, 8)
        updater = MagicMock()
        updater.update_date.return_value = SimpleNamespace(
            target_date=target,
            ohlcv_rows=0,
            investor_rows=0,
            markets_completed=(),
            skipped=False,
            messages=("provider unavailable",),
            metadata={"status": "partial", "source_error_count": 2},
        )
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

        self.assertEqual(3, code)

    def test_confirmed_holiday_keeps_no_new_trading_day_exit(self) -> None:
        target = date(2026, 10, 9)
        repository = MagicMock()
        repository.__enter__.return_value = repository
        repository.settings.provider_delay_seconds = 0
        repository.latest_ohlcv_date.return_value = date(2026, 10, 8)
        updater = MagicMock()
        updater.update_date.return_value = SimpleNamespace(
            target_date=target,
            ohlcv_rows=0,
            investor_rows=0,
            markets_completed=("KOSPI", "KOSDAQ"),
            skipped=True,
            messages=("가격 자료 없음(휴장일 가능)",),
            metadata={"status": "completed", "source_error_count": 0},
        )
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

        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
