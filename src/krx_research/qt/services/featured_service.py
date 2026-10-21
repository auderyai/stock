from __future__ import annotations
from datetime import date
import pandas as pd
from krx_research.daily_research_image import DailyImagePlan, DailyResearchImageImporter
from krx_research.featured_research.repository import FeaturedResearchRepository


class FeaturedResearchService:
    """Qt-free featured-stock application service."""
    def __init__(self) -> None:
        self._images = DailyResearchImageImporter("featured")

    def latest_date(self) -> date | None:
        with FeaturedResearchRepository() as repo:
            dates = repo.available_dates()
        return max(dates) if dates else None

    def query(self, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        with FeaturedResearchRepository(read_only=False) as repo:
            repo.fill_missing_themes(start, end)
            rows = repo.query(start, end)
        return pd.DataFrame(rows)

    def repeated(self, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        with FeaturedResearchRepository() as repo:
            rows = repo.repeated_stocks(start, end)
        return pd.DataFrame(rows)

    def prepare_images(self, files: list[str], report_date: date) -> DailyImagePlan:
        return self._images.prepare(files, report_date)

    def commit_images(self, plan: DailyImagePlan):
        return self._images.commit(plan)

    def refresh_missing(self, start: date, end: date):
        with FeaturedResearchRepository(read_only=False) as repo:
            return repo.refresh_missing(start, end)
