from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from psycopg import sql

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository


class AdministrativeRepository(AbstractContextManager):
    """Explicit boundary for diagnostics, setup and read-only operator queries."""

    def __init__(
        self,
        settings: DataEngineSettings,
        *,
        application_name: str,
        read_only: bool = True,
    ) -> None:
        self._repository = BaseDataRepository(
            settings, application_name=application_name, read_only=read_only
        )

    def __enter__(self) -> "AdministrativeRepository":
        self._repository.__enter__()
        return self

    def __exit__(self, *args) -> None:
        self._repository.__exit__(*args)

    def query(self, statement: str, limit: int) -> tuple[list[str], list[dict[str, Any]], bool]:
        with self._repository.conn.transaction():
            self._repository.conn.execute("SET TRANSACTION READ ONLY")
            self._repository.conn.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{self._repository.settings.statement_timeout}s",),
            )
            cursor = self._repository.conn.execute(statement)
            rows = cursor.fetchmany(limit + 1)
            columns = [getattr(item, "name", item[0]) for item in cursor.description or ()]
        return columns, [dict(row) for row in rows[:limit]], len(rows) > limit

    def server_identity(self) -> dict[str, Any]:
        return dict(self._repository.conn.execute(
            "SELECT current_database() AS db, current_user AS user, version() AS version"
        ).fetchone())

    def grant_reader(self, reader: str) -> dict[str, str]:
        role = sql.Identifier(reader)
        with self._repository.conn.transaction():
            for statement in (
                "GRANT USAGE ON SCHEMA market, market_core TO {}",
                "GRANT SELECT ON ALL TABLES IN SCHEMA market, market_core TO {}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA market_core GRANT SELECT ON TABLES TO {}",
            ):
                self._repository.conn.execute(sql.SQL(statement).format(role))
        return self._repository.database_identity()

    def ls_day(self, day: date) -> dict[str, Any] | None:
        exists = self._repository.conn.execute(
            "SELECT to_regclass('market_core.ls_investor_t1702_raw') AS relation"
        ).fetchone()
        if not exists["relation"]:
            return None
        prices = self._repository.get_market_ohlcv(day, day)
        count = self._repository.conn.execute(
            "SELECT count(*) AS rows,count(DISTINCT stock_code) AS stocks "
            "FROM market_core.ls_investor_t1702_raw "
            "WHERE trade_date=%s AND exchange_code='K'", (day,),
        ).fetchone()
        samples = self._repository.conn.execute(
            "SELECT stock_code,trade_date,metric_code,side_code,source_fields "
            "FROM market_core.ls_investor_t1702_raw "
            "WHERE trade_date=%s AND exchange_code='K' AND stock_code IN "
            "(SELECT DISTINCT stock_code FROM market_core.ls_investor_t1702_raw "
            "WHERE trade_date=%s AND exchange_code='K' ORDER BY stock_code LIMIT 5) "
            "ORDER BY stock_code,metric_code,side_code", (day, day),
        ).fetchall()
        return {
            "prices": prices,
            "count": dict(count),
            "samples": [dict(row) for row in samples],
            "flow": self._repository.get_ls_investor_flow(trade_date=day),
        }
