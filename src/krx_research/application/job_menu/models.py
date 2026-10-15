from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import IntEnum


class JobKind(IntEnum):
    MENU_2 = 2
    MENU_5 = 5
    MENU_7 = 7
    DRIVE_VERIFY = 8
    DRIVE_UPDATE = 9
    DRIVE_CLEANUP = 10


@dataclass(frozen=True)
class JobRequest:
    kind: JobKind
    start: dt.date | None = None
    end: dt.date | None = None
    ticker: str | None = None
    venues: tuple[str, ...] = ("NXT", "COMBINED")
    chunk_days: int = 90
    include_investor: bool = True


@dataclass(frozen=True)
class JobResult:
    kind: JobKind
    return_code: int
    log_path: str
    summary: str

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0


@dataclass(frozen=True)
class LegacyJobSpec:
    key: str
    title: str
    description: str
    batch_name: str = ""
    arguments: tuple[str, ...] = field(default_factory=tuple)
