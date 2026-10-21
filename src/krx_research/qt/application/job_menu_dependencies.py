from __future__ import annotations

from pathlib import Path

from krx_research.database import resolve_database_target
from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.controllers.pattern_search_controller import PatternSearchController
from krx_research.qt.pattern_search import PatternSearchDialog
from krx_research.qt.repositories.pattern_repository import PostgreSQLPatternRepository
from krx_research.qt.services.box_breakout import PeriodPatternSearchService
from krx_research.qt.services.current_pattern import CurrentPatternSearchService
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.pattern_similarity import PatternSimilaritySearchService, PatternVectorCache
from krx_research.qt.services.security_search_service import SecuritySearchService
from krx_research.data_engine.workstation_repository import WorkstationData


class JobMenuDependencies:
    """Composition root for local menu UI dependencies."""

    def __init__(self, root: Path):
        target = resolve_database_target(root, read_only=True)
        repository = PostgreSQLPatternRepository(target)
        self.security_search = SecuritySearchService(WorkstationData(target)).search
        self._controller = PatternSearchController(
            PatternSimilaritySearchService(
                repository, PatternVectorCache(root / ".local_cache" / "pattern_vectors")
            ),
            PeriodPatternSearchService(repository),
            CurrentPatternSearchService(repository),
        )
        self._chart_service = ChartService(WorkstationData(target))

    def pattern_dialog(self, parent=None) -> PatternSearchDialog:
        return PatternSearchDialog(self._controller, self._chart, parent)

    def _chart(self, **options):
        return ChartWindow(self._chart_service, **options)
