from __future__ import annotations

from krx_research.qt.services.ports import SecuritySearchPort


class SecuritySearchService:
    """Stock lookup service used by chart navigation and EMA-similarity selection."""
    def __init__(self, data: SecuritySearchPort):
        self._data = data

    def resolve(self, query: str) -> str:
        return self._data.resolve_ticker(query)

    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        return self._data.search_securities(query, limit=limit)
