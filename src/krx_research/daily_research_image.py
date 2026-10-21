"""Two-step image ingestion for the daily featured-stock and theme screens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from krx_research.database.settings import resolve_database_target
from krx_research.project import STOCK_ROOT
from krx_research.featured_research.parser import FeaturedRow, ParsedFeaturedSpreadsheet
from krx_research.featured_research.repository import FeaturedResearchRepository
from krx_research.research_archive import ResearchArchiveService
from krx_research.research_archive.parsers import CodexImageParser
from krx_research.theme_research.parser import ParsedSpreadsheet, ThemeRow
from krx_research.theme_research.repository import ThemeResearchRepository

DailyKind = Literal["featured", "theme"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True, slots=True)
class DailyImagePlan:
    kind: DailyKind
    documents: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DailyImageImportResult:
    dates: tuple[date, ...]
    row_count: int
    matched_count: int
    unmatched_count: int


class DailyResearchImageImporter:
    """Archive image evidence, preview DB reconciliation, then commit on approval."""

    def __init__(self, kind: DailyKind, root: str | Path = STOCK_ROOT) -> None:
        if kind not in {"featured", "theme"}:
            raise ValueError(f"지원하지 않는 일일자료 유형: {kind}")
        self.kind, self.root = kind, Path(root).resolve()
        self.target = resolve_database_target(self.root)
        self.archive = ResearchArchiveService(self.target, self.root)

    def prepare(self, files: list[str], report_date: date) -> DailyImagePlan:
        if not isinstance(report_date, date):
            raise TypeError("입력일이 올바르지 않습니다.")
        sources = self._sources(files)
        self.archive.initialize()
        parser = CodexImageParser(self.root)
        document_ids: list[str] = []
        for source in sources:
            digest = self.archive.layout.file_sha256(source)
            existing = self.archive.document_by_sha256(digest)
            if existing:
                if str(existing["document_kind"]) != "IMAGE":
                    raise ValueError(f"이미지 원본과 동일한 해시의 다른 자료가 있습니다: {source.name}")
                document_ids.append(str(existing["document_id"]))
                continue
            parsed = parser.parse(source, report_date=report_date)
            if not parsed.observations:
                raise ValueError(f"종목을 한 건도 읽지 못했습니다: {source.name}")
            document_ids.append(self.archive.store_parsed(parsed)["document_id"])
        unique_ids = tuple(dict.fromkeys(document_ids))
        records = self.archive.document_observations(list(unique_ids), report_date)
        rows = tuple(self._normalized(record, report_date) for record in records)
        if not rows:
            raise ValueError("등록할 종목을 찾지 못했습니다.")
        if self.kind == "featured" and any(not row["reason"] for row in rows):
            raise ValueError("특징주 이미지에서 사유가 비어 있는 종목이 있습니다. 원본을 확인하십시오.")
        if self.kind == "theme" and any(not row["category"] for row in rows):
            raise ValueError("테마 이미지에서 테마명이 비어 있는 종목이 있습니다. 원본을 확인하십시오.")
        return DailyImagePlan(self.kind, unique_ids, rows)

    def commit(self, plan: DailyImagePlan) -> DailyImageImportResult:
        if plan.kind != self.kind:
            raise ValueError("미리보기 자료 유형이 현재 화면과 다릅니다.")
        totals = [0, 0, 0]
        dates: list[date] = []
        for report_date, rows in self._by_date(plan.rows).items():
            digest = self._batch_digest(report_date, rows)
            file_name = " + ".join(dict.fromkeys(str(row["original_filename"]) for row in rows))
            if self.kind == "featured":
                parsed = ParsedFeaturedSpreadsheet(
                    self.root, file_name, digest, "Codex image", report_date,
                    tuple(self._featured_row(index, row) for index, row in enumerate(rows, 1)),
                )
                with FeaturedResearchRepository(read_only=False) as repository:
                    repository.initialize_schema()
                    existing = repository.find_batch_by_sha256(digest)
                    matched, unmatched = ((int(existing["matched_count"]), int(existing["unmatched_count"]))
                                          if existing else repository.insert_spreadsheet(parsed)[1:])
            else:
                parsed = ParsedSpreadsheet(
                    self.root, file_name, digest, "Codex image", report_date,
                    tuple(self._theme_row(index, row) for index, row in enumerate(rows, 1)),
                )
                with ThemeResearchRepository(read_only=False) as repository:
                    repository.initialize_schema()
                    existing = repository.find_batch_by_sha256(digest)
                    result = None if existing else repository.insert_spreadsheet(parsed)
                    matched, unmatched = ((int(existing["matched_count"]), int(existing["unmatched_count"]))
                                          if existing else (result[1], result[2]))
            dates.append(report_date); totals[0] += len(rows); totals[1] += matched; totals[2] += unmatched
        return DailyImageImportResult(tuple(dates), *totals)

    @staticmethod
    def _sources(files: list[str]) -> tuple[Path, ...]:
        sources = tuple(dict.fromkeys(Path(value).expanduser().resolve() for value in files))
        if not sources:
            raise ValueError("선택한 이미지가 없습니다.")
        for source in sources:
            if source.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(f"PNG/JPG/WEBP 이미지만 등록할 수 있습니다: {source.name}")
            if not source.is_file():
                raise FileNotFoundError(source)
        return sources

    @staticmethod
    def _normalized(record: dict[str, Any], report_date: date) -> dict[str, Any]:
        source_return = record.get("source_return_pct")
        db_return = record.get("db_return_pct")
        source_value = record.get("source_trading_value_eok")
        db_value = record.get("db_trading_value_eok")
        return {
            **record, "report_date": report_date,
            "document_id": str(record["document_id"]),
            "category": str(record.get("category") or "").strip(),
            "ticker": str(record.get("ticker") or "").strip() or None,
            "stock_name": str(record.get("stock_name") or "").strip(),
            "reason": str(record.get("reason") or "").strip(),
            "source_return_pct": float(source_return) if source_return is not None else None,
            "db_return_pct": float(db_return) if db_return is not None else None,
            "final_return_pct": float(db_return) if db_return is not None else None,
            "source_trading_value_eok": float(source_value) if source_value is not None else None,
            "db_trading_value_eok": float(db_value) if db_value is not None else None,
            "final_trading_value_eok": float(db_value) if db_value is not None else None,
        }

    @staticmethod
    def _by_date(rows: tuple[dict[str, Any], ...]) -> dict[date, list[dict[str, Any]]]:
        grouped: dict[date, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["report_date"], []).append(row)
        return grouped

    def _batch_digest(self, report_date: date, rows: list[dict[str, Any]]) -> str:
        documents = sorted({str(row["document_id"]) for row in rows})
        return sha256(f"{self.kind}|{report_date}|{'|'.join(documents)}".encode()).hexdigest()

    @staticmethod
    def _raw(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "document_id": row["document_id"], "authority": row.get("authority"),
            "source_return_pct": row["source_return_pct"],
            "source_trading_value_eok": row["source_trading_value_eok"],
            "db_return_pct": row["db_return_pct"],
            "db_trading_value_eok": row["db_trading_value_eok"],
        }

    def _featured_row(self, index: int, row: dict[str, Any]) -> FeaturedRow:
        return FeaturedRow(index, row["report_date"], row["ticker"], row["stock_name"],
                           row["final_return_pct"], None, row["category"] or None,
                           row["reason"], self._raw(row))

    def _theme_row(self, index: int, row: dict[str, Any]) -> ThemeRow:
        return ThemeRow(index, row["report_date"], row["ticker"], row["stock_name"],
                        row["final_return_pct"], None, row["category"], row["reason"],
                        self._raw(row))


__all__ = ["DailyImageImportResult", "DailyImagePlan", "DailyResearchImageImporter"]
