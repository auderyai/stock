from __future__ import annotations

from datetime import date
from typing import Any

from .models import FinancialPeriod


class FinancialBackfillPolicy:
    """One ordering rule for cloud collection and local approval."""

    PERIODS = tuple(FinancialPeriod)
    CURRENT_YEAR_RELEASES = {
        FinancialPeriod.Q1: (6, 1),
        FinancialPeriod.HALF: (8, 31),
        FinancialPeriod.Q3: (11, 30),
    }

    @staticmethod
    def validate_year(year: int, *, today: date | None = None) -> int:
        current = (today or date.today()).year
        if not 2015 <= year <= current:
            raise ValueError(f"사업연도는 2015~{current}만 가능합니다: {year}")
        return year

    @classmethod
    def available_periods(
        cls, year: int, *, today: date | None = None
    ) -> tuple[FinancialPeriod, ...]:
        current = today or date.today()
        cls.validate_year(year, today=current)
        if year < current.year:
            return cls.PERIODS
        return tuple(
            period
            for period, (month, day) in cls.CURRENT_YEAR_RELEASES.items()
            if current >= date(year, month, day)
        )

    @classmethod
    def next_period(
        cls,
        year_state: dict[str, Any],
        targets: tuple[FinancialPeriod, ...] | None = None,
    ) -> FinancialPeriod | None:
        periods = year_state.get("periods") or {}
        return next(
            (
                period
                for period in targets or cls.PERIODS
                if not periods.get(period.label, {}).get("cloud_completed")
            ),
            None,
        )

    @staticmethod
    def extend_year_order(stored: list[int], requested: list[int]) -> list[int]:
        if stored == requested:
            return stored
        if len(stored) <= len(requested) and requested[-len(stored):] == stored:
            return requested
        raise RuntimeError("기존 재무 백필 사업연도 순서와 요청이 다릅니다.")
