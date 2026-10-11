from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceObservation:
    stock_name: str
    ticker: str | None = None
    category: str = ""
    reason: str = ""
    source_return_pct: float | None = None
    source_trading_value_eok: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedResearchSource:
    path: Path
    kind: str
    report_date: date
    title: str
    provider: str = ""
    ticker: str | None = None
    company_name: str = ""
    pages: tuple[str, ...] = ()
    observations: tuple[SourceObservation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
