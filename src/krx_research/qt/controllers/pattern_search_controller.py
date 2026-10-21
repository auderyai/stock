from __future__ import annotations

from collections.abc import Callable

from krx_research.qt.models.pattern_queries import (
    CurrentPatternQuery, PatternSearchQuery, PeriodPatternQuery,
)
from krx_research.qt.services.box_breakout import PeriodPatternSearchService
from krx_research.qt.services.current_pattern import CurrentPatternSearchService
from krx_research.qt.services.pattern_similarity import PatternSimilaritySearchService


class PatternSearchController:
    """Coordinates pattern-search use cases without UI or database dependencies."""

    def __init__(self, similarity: PatternSimilaritySearchService,
                 period: PeriodPatternSearchService,
                 current: CurrentPatternSearchService):
        self._similarity, self._period, self._current = similarity, period, current

    def suggest_securities(self, query: str) -> list[dict[str, str]]:
        return self._similarity.suggest_securities(query)

    def command(self, query: PatternSearchQuery | PeriodPatternQuery | CurrentPatternQuery
                ) -> Callable[[], list[dict]]:
        service = (self._current if isinstance(query, CurrentPatternQuery) else
                   self._period if isinstance(query, PeriodPatternQuery) else self._similarity)
        return lambda: service.search(query)
