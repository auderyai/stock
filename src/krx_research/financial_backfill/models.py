from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


class FinancialPeriod(Enum):
    Q1 = ("Q1", "11013", 3, 31)
    HALF = ("HALF", "11012", 6, 30)
    Q3 = ("Q3", "11014", 9, 30)
    ANNUAL = ("ANNUAL", "11011", 12, 31)

    def __init__(self, label: str, report_code: str, month: int, day: int) -> None:
        self.label = label
        self.report_code = report_code
        self.month = month
        self.day = day

    def period_end(self, year: int) -> date:
        return date(year, self.month, self.day)

    @classmethod
    def parse(cls, value: str) -> "FinancialPeriod":
        normalized = value.strip().upper()
        for period in cls:
            if normalized in {period.label, period.report_code}:
                return period
        raise ValueError(f"지원하지 않는 재무기간입니다: {value}")


@dataclass(frozen=True, slots=True)
class DartCompany:
    corp_code: str
    ticker: str
    name: str
    english_name: str
    modified_at: date | None


@dataclass(frozen=True, slots=True)
class FinancialBatch:
    companies: tuple[DartCompany, ...]
    facts: tuple[dict[str, Any], ...]

    @property
    def fact_count(self) -> int:
        return len(self.facts)
