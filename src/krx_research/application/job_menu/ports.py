from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .models import JobRequest, JobResult, LegacyJobSpec

Progress = Callable[[str], None]


class JobExecutorPort(Protocol):
    def execute(self, request: JobRequest, progress: Progress | None = None) -> JobResult: ...
    def execute_legacy(self, spec: LegacyJobSpec, progress: Progress | None = None) -> JobResult: ...
    def cancel(self) -> None: ...
