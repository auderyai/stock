"""Structural ports used by Qt-free application services."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol


class ScreeningDataPort(Protocol):
    def available_screen_dates(self, limit: int = 500, *, quote_venue: str = "KRX") -> list[dt.date]: ...

    def load_screen_period(self, screen_type: str, **options: Any) -> Any: ...


class ChartDataPort(Protocol):
    def resolve_ticker(self, ticker_or_name: str) -> str: ...

    def load_chart(self, ticker: str, **options: Any) -> Any: ...


class SecuritySearchPort(Protocol):
    def resolve_ticker(self, ticker_or_name: str) -> str: ...

    def search_securities(self, query: str, *, limit: int = 20) -> list[dict[str, str]]: ...


class ErrorLogPort(Protocol):
    def write(self, trace_text: str) -> Any: ...
