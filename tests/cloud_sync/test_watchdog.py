from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import unittest


SPEC = importlib.util.spec_from_file_location(
    "stock_drive_watchdog", Path(__file__).parents[2] / "scripts" / "stock_drive_watchdog.py"
)
WATCHDOG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = WATCHDOG
SPEC.loader.exec_module(WATCHDOG)
WatchdogPolicy, WorkflowRun, run = WATCHDOG.WatchdogPolicy, WATCHDOG.WorkflowRun, WATCHDOG.run


def record(run_id=1, status="completed", conclusion="failure"):
    return WorkflowRun(run_id, datetime(2026, 10, 16, 12, tzinfo=timezone.utc), status, conclusion, f"https://example/{run_id}")


class _Client:
    def __init__(self, runs=(), code_failure=False):
        self.rows, self.code_failure = list(runs), code_failure
        self.dispatched, self.reported = [], []

    def runs_since(self, cutoff): return self.rows
    def has_code_failure(self, run_id): return self.code_failure
    def dispatch(self, target): self.dispatched.append(target)
    def report_exhausted(self, target, runs): self.reported.append((target, runs))


class WatchdogTests(unittest.TestCase):
    def test_target_day_uses_previous_day_before_evening(self):
        self.assertEqual(str(WatchdogPolicy.target_day(datetime(2026, 10, 17, 0, 20, tzinfo=timezone.utc))), "2026-10-16")

    def test_missing_run_dispatches_once(self):
        client = _Client()
        self.assertEqual(run(client, datetime(2026, 10, 16).date()), "dispatch")
        self.assertEqual(len(client.dispatched), 1)

    def test_active_or_successful_run_is_not_duplicated(self):
        for row, expected in ((record(status="in_progress", conclusion=None), "wait"),
                              (record(conclusion="success"), "complete")):
            client = _Client([row]); self.assertEqual(run(client, datetime(2026, 10, 16).date()), expected)
            self.assertFalse(client.dispatched)

    def test_code_failure_waits_for_codex_repair(self):
        client = _Client([record()], code_failure=True)
        self.assertEqual(run(client, datetime(2026, 10, 16).date()), "codex-repair")
        self.assertFalse(client.dispatched)

    def test_provider_failure_retries_once_then_reports(self):
        target = datetime(2026, 10, 16).date()
        first = _Client([record()]); self.assertEqual(run(first, target), "retry")
        exhausted = _Client([record(2), record(1)])
        self.assertEqual(run(exhausted, target), "exhausted")
        self.assertEqual(len(exhausted.reported), 1)

    def test_weekend_never_dispatches(self):
        client = _Client(); self.assertEqual(run(client, datetime(2026, 10, 17).date()), "weekend")
        self.assertFalse(client.dispatched)


if __name__ == "__main__": unittest.main()
