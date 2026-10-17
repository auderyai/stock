from __future__ import annotations

from collections.abc import Callable

from krx_research.qt.services.box_breakout import PeriodPatternQuery, PeriodPatternSearchService
from krx_research.qt.services.pattern_similarity import (
    PatternSearchQuery, PatternSimilaritySearchService,
)


class PatternSearchController:
    """Coordinates pattern-search use cases without UI or database dependencies."""

    def __init__(self, similarity: PatternSimilaritySearchService,
                 period: PeriodPatternSearchService):
        self._similarity, self._period = similarity, period

    def suggest_securities(self, query: str) -> list[dict[str, str]]:
        return self._similarity.suggest_securities(query)

    def command(self, query: PatternSearchQuery | PeriodPatternQuery) -> Callable[[], list[dict]]:
        service = self._period if isinstance(query, PeriodPatternQuery) else self._similarity
        return lambda: service.search(query)
