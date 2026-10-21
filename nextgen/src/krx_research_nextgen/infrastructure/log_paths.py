from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from krx_research.project import STOCK_ROOT


@dataclass(frozen=True)
class LogPaths:
    """Single source of truth for every project log path."""

    root: Path = STOCK_ROOT

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def runtime(self) -> Path:
        return self.logs / "runtime"

    @property
    def database(self) -> Path:
        return self.logs / "database"

    @property
    def tasks(self) -> Path:
        return self.logs / "tasks"

    @property
    def plans(self) -> Path:
        return self.logs / "plans"

    def task_day(self, day: str | None = None) -> Path:
        return self.tasks / (day or datetime.now().strftime("%Y%m%d"))

    def plan_day(self, day: str | None = None) -> Path:
        return self.plans / (day or datetime.now().strftime("%Y%m%d"))

    def ensure(self) -> "LogPaths":
        for path in (self.logs, self.runtime, self.database, self.tasks, self.plans):
            path.mkdir(parents=True, exist_ok=True)
        return self


LOG_PATHS = LogPaths().ensure()
