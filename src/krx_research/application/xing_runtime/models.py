from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TrQualificationResult:
    tr_code: str
    passed: bool
    row_count: int
    message: str
    sample: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class QualificationReport:
    login_passed: bool
    results: tuple[TrQualificationResult, ...]
    stock_code: str = ""
    sector_code: str = ""

    @property
    def passed(self) -> bool:
        return self.login_passed and bool(self.results) and all(item.passed for item in self.results)

    @property
    def failed_trs(self) -> tuple[str, ...]:
        return tuple(item.tr_code for item in self.results if not item.passed)
