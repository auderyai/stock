from __future__ import annotations

from krx_research_nextgen.models.screening import (
    DateRange,
    RepeatedScreenResult,
    ScreeningKind,
    ScreeningQuery,
    ScreeningResult,
)
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.screening_export_service import ScreeningExportService
from krx_research_nextgen.presentation.repeated_screen_table import HEADERS as REPEATED_HEADERS, row_values as repeated_values


class ScreeningController:
    def __init__(self, service: ScreeningService, exporter: ScreeningExportService | None = None) -> None:
        self._service = service
        self._exporter = exporter or ScreeningExportService()

    @staticmethod
    def kinds() -> list[ScreeningKind]:
        return list(ScreeningKind)

    def run(
        self,
        kind: ScreeningKind,
        *,
        limit: int = 100,
        market: str = "ALL",
        comparison_ticker: str = "005930",
        near_low: float = -10.0,
        near_high: float = 0.0,
        as_of_date: str | None = None,
        period: DateRange | None = None,
    ) -> list[ScreeningResult]:
        return self._service.run(
            ScreeningQuery(
                kind=kind, limit=limit, market=market,
                comparison_ticker=comparison_ticker,
                near_low=near_low, near_high=near_high,
                as_of_date=as_of_date,
            ), period=period,
        )

    def status(self) -> dict[str, str]:
        return self._service.status()

    def run_repeated(
        self, kind: ScreeningKind, period: DateRange, *, limit: int, market: str,
        comparison_ticker: str = "005930", near_low: float = -10.0, near_high: float = 0.0,
    ) -> list[RepeatedScreenResult]:
        query = ScreeningQuery(kind, limit, market, comparison_ticker, near_low, near_high)
        return self._service.run_repeated(query, period)

    def export(self, rows: list[ScreeningResult], path: str) -> None:
        self._exporter.export(rows, path)

    def export_repeated(self, rows: list[RepeatedScreenResult], path: str) -> None:
        self._exporter.export_table(REPEATED_HEADERS, [repeated_values(row) for row in rows], path, "기간 내 다빈도 종목")
