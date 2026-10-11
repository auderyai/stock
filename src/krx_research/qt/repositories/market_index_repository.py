from __future__ import annotations

from krx_research.data_engine.market_indices import fetch_index, index_list_snapshots, list_indices
from krx_research.data_engine.postgresql import BaseDataRepository


class MarketIndexRepository:
    """PostgreSQL/SQL repository for KRX composite and sector indices."""

    def __init__(self, settings):
        self._settings = settings

    def list_entries(self) -> list[dict]:
        with BaseDataRepository(self._settings) as repo:
            return [dict(row) for row in list_indices(repo.conn)]

    def list_snapshots(self) -> list[dict]:
        with BaseDataRepository(self._settings) as repo:
            return [dict(row) for row in index_list_snapshots(repo.conn)]

    def fetch_bars(self, code: str):
        with BaseDataRepository(self._settings) as repo:
            return fetch_index(repo.conn, str(code))
