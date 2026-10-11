from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class UpdateResult:
    target_date: date
    ohlcv_rows: int = 0
    investor_rows: int = 0
    markets_completed: tuple[str, ...] = ()
    skipped: bool = False
    messages: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataCoverage:
    dataset: str
    minimum_date: date | None
    maximum_date: date | None
    row_count: int
