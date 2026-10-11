from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.job_menu import (
    JobKind, JobRequest, JobResult, LegacyJobSpec, Menu257ApplicationService,
)


class FakeExecutor:
    def __init__(self) -> None:
        self.requests = []
        self.cancelled = False

    def execute(self, request, progress=None):
        self.requests.append(request)
        if progress:
            progress("progress")
        return JobResult(request.kind, 0, "fake.log", "ok")

    def execute_legacy(self, spec, progress=None):
        self.requests.append(spec)
        return JobResult(JobKind.MENU_2, 0, "fake.log", "ok")

    def cancel(self):
        self.cancelled = True


fake = FakeExecutor()
service = Menu257ApplicationService(fake)
messages = []
assert service.run(JobRequest(JobKind.MENU_2, end=dt.date(2026, 10, 2)), messages.append).succeeded
assert service.run(JobRequest(JobKind.MENU_5, start=dt.date(2026, 10, 1), end=dt.date(2026, 10, 2))).succeeded
assert service.run(JobRequest(JobKind.MENU_7, start=dt.date(2026, 10, 1), end=dt.date(2026, 10, 2), venues=("COMBINED",))).succeeded
assert messages == ["progress"]
service.cancel(); assert fake.cancelled
try:
    service.run(JobRequest(JobKind.MENU_5, start=dt.date(2026, 10, 3), end=dt.date(2026, 10, 2)))
except ValueError:
    pass
else:
    raise AssertionError("invalid date range was not rejected")
print("V42_GUI_UNIT: PASS")
