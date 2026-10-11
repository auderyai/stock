"""Idempotent import service for daily featured-stock workbooks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .parser import parse_featured_spreadsheet
from .repository import FeaturedResearchRepository


@dataclass(frozen=True, slots=True)
class ImportResult:
    report_date: date
    file_name: str
    row_count: int
    matched_count: int
    unmatched_count: int
    skipped: bool
    batch_id: str


class FeaturedSpreadsheetImporter:
    def __init__(self, repository: FeaturedResearchRepository) -> None:
        self.repository = repository

    def import_file(self, path: str | Path) -> ImportResult:
        parsed = parse_featured_spreadsheet(path)
        duplicate = self.repository.find_batch_by_sha256(parsed.file_sha256)
        if duplicate is not None:
            self.repository.fill_missing_themes(parsed.report_date, parsed.report_date)
            self.repository.refresh_missing(parsed.report_date, parsed.report_date)
            return ImportResult(
                report_date=parsed.report_date,
                file_name=parsed.file_name,
                row_count=int(duplicate["row_count"]),
                matched_count=int(duplicate["matched_count"]),
                unmatched_count=int(duplicate["unmatched_count"]),
                skipped=True,
                batch_id=str(duplicate["batch_id"]),
            )
        batch_id, matched, unmatched = self.repository.insert_spreadsheet(parsed)
        return ImportResult(
            report_date=parsed.report_date,
            file_name=parsed.file_name,
            row_count=len(parsed.rows),
            matched_count=matched,
            unmatched_count=unmatched,
            skipped=False,
            batch_id=batch_id,
        )


__all__ = ["FeaturedSpreadsheetImporter", "ImportResult"]
