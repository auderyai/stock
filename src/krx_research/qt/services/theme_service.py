from __future__ import annotations
from datetime import date
import pandas as pd
from krx_research.daily_research_image import DailyImagePlan, DailyResearchImageImporter
from krx_research.theme_research.repository import ThemeResearchRepository


class ThemeResearchService:
    """Qt-free theme-research application service."""
    def __init__(self) -> None:
        self._images = DailyResearchImageImporter("theme")

    def latest_date(self) -> date | None:
        with ThemeResearchRepository() as repo:
            dates = repo.available_dates()
        return max(dates) if dates else None

    def query(self, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        with ThemeResearchRepository() as repo:
            rows = repo.query(start, end)
        return pd.DataFrame(rows)

    def prepare_images(self, files: list[str], report_date: date) -> DailyImagePlan:
        return self._images.prepare(files, report_date)

    def commit_images(self, plan: DailyImagePlan):
        return self._images.commit(plan)

    def refresh(self, start: date, end: date):
        with ThemeResearchRepository(read_only=False) as repo:
            return repo.refresh_trading_values(start, end)
