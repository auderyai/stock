from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import IntEnum


class MenuAction(IntEnum):
    FAST_DAILY = 2
    INVESTOR_RAW = 5
    STOCK_SUPPLEMENT = 7


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    passed: bool
    affected_rows: int = 0
    message: str = ""


@dataclass(frozen=True, slots=True)
class ActionReport:
    action: MenuAction
    started_at: dt.datetime
    finished_at: dt.datetime
    stages: tuple[StageResult, ...]
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.stages) and all(stage.passed for stage in self.stages)

    @property
    def affected_rows(self) -> int:
        return sum(stage.affected_rows for stage in self.stages)

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(stage.name for stage in self.stages if not stage.passed)
