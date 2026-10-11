from __future__ import annotations

import pandas as pd

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.market_indices import fetch_index
from krx_research.data_engine.postgresql import BaseDataRepository


class ScenarioMarketRepository:
    """Read-only PostgreSQL/SQL access for scenario market-index context."""

    _INDEX_CODES = {"KOSPI": "1001", "KOSDAQ": "2001"}

    @classmethod
    def index_name(cls, market: str) -> str:
        text = str(market or "").upper()
        if "KOSDAQ" in text or "코스닥" in text:
            return "KOSDAQ"
        if "KOSPI" in text or "코스피" in text:
            return "KOSPI"
        return ""

    def load_index(self, market: str) -> pd.DataFrame:
        name = self.index_name(market)
        if not name:
            return pd.DataFrame()
        with BaseDataRepository(
            DataEngineSettings.from_environment(),
            application_name="scenario_index_read",
        ) as repo:
            return fetch_index(repo.conn, self._INDEX_CODES[name])
