from __future__ import annotations

from datetime import date
from collections.abc import Callable, Sequence
from typing import Protocol


class DailyResearchService(Protocol):
    def latest_date(self) -> date | None: ...
    def query(self, start: date, end: date): ...
    def prepare_images(self, paths: Sequence[str], report_date: date): ...
    def commit_images(self, plan): ...


class DailyResearchController:
    """Expose daily-research use cases without leaking services into the View."""

    def __init__(
        self,
        service: DailyResearchService,
        *,
        refresh: Callable[[date, date], object],
        repeated: Callable[[date, date], object] | None = None,
    ) -> None:
        self._service = service
        self._refresh = refresh
        self._repeated = repeated

    def latest_date(self) -> date | None:
        return self._service.latest_date()

    def query(self, start: date, end: date):
        return self._service.query(start, end)

    def repeated(self, start: date, end: date):
        if self._repeated is None:
            raise ValueError("기간 중복 종목은 특징주에서만 지원합니다.")
        return self._repeated(start, end)

    def refresh(self, start: date, end: date):
        return self._refresh(start, end)

    def prepare_images(self, paths: Sequence[str], report_date: date):
        return self._service.prepare_images(paths, report_date)

    def commit_images(self, plan):
        return self._service.commit_images(plan)
