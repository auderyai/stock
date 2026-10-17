from __future__ import annotations

from datetime import date
from typing import Any

from .models import FinancialPeriod


class FinancialBackfillPolicy:
    """One ordering rule for cloud collection and local approval."""

    PERIODS = tuple(FinancialPeriod)

    @staticmethod
    def validate_year(year: int, *, today: date | None = None) -> int:
        latest_complete = (today or date.today()).year - 1
        if not 2015 <= year <= latest_complete:
            raise ValueError(f"완료 사업연도는 2015~{latest_complete}만 가능합니다: {year}")
        return year

    @classmethod
    def next_period(cls, year_state: dict[str, Any]) -> FinancialPeriod | None:
        periods = year_state.get("periods") or {}
        return next(
            (
                period
                for period in cls.PERIODS
                if not periods.get(period.label, {}).get("cloud_completed")
            ),
            None,
        )

    @staticmethod
    def require_previous_local_completion(
        years: list[int], metadata: dict[str, Any], requested_year: int
    ) -> None:
        index = years.index(requested_year)
        if index and not (
            (metadata.get("years") or {}).get(str(years[index - 1]), {}).get("local_completed")
        ):
            raise RuntimeError(
                f"{years[index - 1]}년 로컬 검증 완료 후 {requested_year}년을 시작할 수 있습니다."
            )
