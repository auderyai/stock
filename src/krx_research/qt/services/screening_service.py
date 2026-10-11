from __future__ import annotations

import datetime as dt
import re
from dataclasses import replace

import numpy as np

from krx_research.qt.models.screen_query import ScreenQuery
from krx_research.ui.data import WorkstationData, describe_screen_freshness, filter_52w_distance


class ScreeningService:
    """Application service for screen queries. Qt-free and independently testable."""

    def __init__(self, data: WorkstationData):
        self._data = data

    def available_dates(self, *, quote_venue: str, limit: int = 1000) -> list[dt.date]:
        return list(self._data.available_screen_dates(limit=limit, quote_venue=quote_venue))

    def execute(self, query: ScreenQuery):
        query.validate()
        dataset = self._data.load_screen_period(
            query.screen_key,
            start_date=query.start_date,
            end_date=query.end_date,
            data_source_mode=query.source_mode,
            quote_venue=query.quote_venue,
            comparison_ticker=query.comparison_ticker,
        )
        if query.screen_key == "near_high_52w":
            dataset = filter_52w_distance(dataset, query.near_52w_low, query.near_52w_high)
        return self._limit(dataset, query.top_n)

    @staticmethod
    def _limit(dataset, top_n: int):
        """Apply one global rank limit after domain ranking, without duplicating UI logic."""
        rows = dataset.rows.head(int(top_n)).copy().reset_index(drop=True)
        if "rank" in rows.columns:
            rows["rank"] = np.arange(1, len(rows) + 1, dtype="int64")
        run = dict(dataset.run or {})
        run["top_n"] = int(top_n)
        title = re.sub(r"Top(?:\s*\d+)?", f"Top {int(top_n)}", str(dataset.title), flags=re.I)
        return replace(dataset, rows=rows, run=run, title=title)

    @staticmethod
    def freshness(dataset) -> str:
        try:
            return describe_screen_freshness(dataset)
        except Exception:
            return ""
