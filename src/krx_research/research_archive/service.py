from __future__ import annotations

import mimetypes
import os
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from krx_research.archive.paths import ArchiveLayout
from .parsers import BrokerPdfParser, CodexImageParser, OpenAIImageParser
from .repository import ResearchArchiveRepository
from .models import ParsedResearchSource


class ResearchArchiveService:
    """Application boundary for immutable originals, extraction and DB reconciliation."""

    def __init__(self, database_target, root: str | Path = Path(r"C:\stock")):
        self.database_target, self.layout = database_target, ArchiveLayout(root)

    def initialize(self) -> None:
        self.layout.ensure()
        with ResearchArchiveRepository(self.database_target) as repository:
            repository.initialize_schema()

    def grant_reader(self, role: str) -> None:
        """Explicit one-time setup; never runs as a side effect of opening the UI."""
        with ResearchArchiveRepository(self.database_target) as repository:
            repository.initialize_schema(reader_role=role)

    def import_files(self, files: list[str]) -> list[dict[str, str]]:
        self.initialize()
        results = []
        for value in files:
            source = Path(value).resolve()
            suffix = source.suffix.lower()
            image_parser = (OpenAIImageParser if os.environ.get("KRX_RESEARCH_IMAGE_PROVIDER") == "openai_api"
                            else CodexImageParser)
            parsed = (BrokerPdfParser().parse(source) if suffix == ".pdf"
                      else image_parser(self.layout.project_root).parse(source))
            results.append(self.store_parsed(parsed))
        return results

    def store_parsed(self, parsed: ParsedResearchSource) -> dict[str, str]:
        """Persist one already-extracted source without invoking the extractor twice."""
        self.initialize()
        source = parsed.path.resolve()
        digest = self.layout.file_sha256(source)
        target = self.layout.research_source_path(
            source, parsed.report_date, ticker=parsed.ticker,
            company_name=parsed.company_name, title=parsed.title,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            shutil.copy2(source, temporary)
            temporary.replace(target)
        elif self.layout.file_sha256(target) != digest:
            raise RuntimeError(f"보관 경로 충돌: {target}")
        with ResearchArchiveRepository(self.database_target) as repository:
            document_id = repository.insert(
                parsed, digest=digest, canonical_path=self.layout.relative_path(target),
                mime_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                file_size=source.stat().st_size,
            )
        return {"document_id": document_id, "file": source.name, "stored": str(target),
                "date": parsed.report_date.isoformat()}

    def document_observations(self, document_ids: list[str], report_date: date | None = None) -> list[dict]:
        with ResearchArchiveRepository(self.database_target, read_only=True) as repository:
            return (repository.reconciled_document_observations(document_ids, report_date)
                    if report_date else repository.document_observations(document_ids))

    def document_by_sha256(self, digest: str) -> dict | None:
        with ResearchArchiveRepository(self.database_target, read_only=True) as repository:
            return repository.by_sha256(digest)

    def query(self, start: date, end: date, search: str = "") -> pd.DataFrame:
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        self.initialize()
        with ResearchArchiveRepository(self.database_target) as repository:
            return pd.DataFrame(repository.query(start, end, search))

    def search(self, query: str, limit: int = 50,
               period: tuple[date, date] | None = None) -> list[dict]:
        text = str(query).strip()
        if not text:
            return []
        if period and period[0] > period[1]:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        with ResearchArchiveRepository(self.database_target, read_only=True) as repository:
            return repository.search_text(text, limit, period=period)
