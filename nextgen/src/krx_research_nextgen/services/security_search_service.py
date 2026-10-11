from __future__ import annotations

from krx_research_nextgen.infrastructure.task_logging import TaskLog
from krx_research_nextgen.models.security import SecurityRecord
from krx_research_nextgen.repositories.security_repository import SecurityRepository


class SecuritySearchService:
    def __init__(self, repository: SecurityRepository) -> None:
        self._repository = repository

    def search(self, keyword: str = "", limit: int = 300) -> list[SecurityRecord]:
        with TaskLog(
            "security_search",
            keyword=keyword,
            limit=limit,
            relation=self._repository.relation_name,
        ) as task:
            rows = self._repository.search(keyword=keyword, limit=limit)
            task.info(f"result_count={len(rows)}")
            return rows

    @property
    def source_relation(self) -> str:
        return self._repository.relation_name
