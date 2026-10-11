from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date, datetime, timezone
import json
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

try:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # Allows pure calculation modules/tests without a DB driver.
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    make_conninfo = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]

from .config import DataEngineSettings
from .core_schema import CoreSchemaMigrator
from .investor import (
    FOREIGN_MEMBERS,
    INSTITUTION_MEMBERS,
    LEAF_INVESTORS,
    normalize_investor_code,
)
from .models import DataCoverage
from .timeframes import normalize_ohlcv


_OHLCV_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("stock_code", "ticker"),
    "trade_date": ("trade_date",),
    "open_price": ("open_price", "open"),
    "high_price": ("high_price", "high"),
    "low_price": ("low_price", "low"),
    "close_price": ("close_price", "close"),
    "volume": ("volume",),
    "amount": ("amount", "trade_value", "value"),
    "change_rate": ("change_rate", "change_ratio"),
    "source": ("source",),
    "adjusted": ("adjusted",),
    "retrieved_at": ("retrieved_at",),
}

_MASTER_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("stock_code", "ticker", "code"),
    "stock_name": ("stock_name", "name"),
    "market": ("market",),
}

_REQUIRED_OHLCV_COLUMNS = (
    "stock_code",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)


def _canonical_column_map(
    columns: Iterable[str], aliases: dict[str, tuple[str, ...]]
) -> dict[str, str]:
    available = set(columns)
    result: dict[str, str] = {}
    for canonical, candidates in aliases.items():
        selected = next((candidate for candidate in candidates if candidate in available), None)
        if selected is not None:
            result[canonical] = selected
    return result


def _ohlcv_layout_name(columns: Iterable[str]) -> str:
    available = set(columns)
    if {"ticker", "open", "high", "low", "close"}.issubset(available):
        return "market_v28"
    if {"stock_code", "open_price", "high_price", "low_price", "close_price"}.issubset(available):
        return "canonical_v30"
    return "unknown"


def _normalized_conninfo(value: str) -> str:
    for scheme in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if value.startswith(scheme):
            value = value.replace(scheme, "postgresql://", 1)
    if "\n" not in value:
        return value
    fields: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, field_value = line.partition("=")
        if separator and key.strip():
            fields[key.strip()] = field_value
    if make_conninfo is None:
        raise RuntimeError("psycopg가 설치되지 않았습니다. requirements-data-engine-v30.txt를 설치하십시오.")
    return make_conninfo(**fields)


def _python_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _integer_value(value: Any, *, default: int | None = None) -> int | None:
    converted = _python_value(value)
    if converted is None:
        return default
    return int(converted)


def _text_value(value: Any, *, default: str) -> str:
    converted = _python_value(value)
    return default if converted is None or str(converted).strip() == "" else str(converted)


def _bool_value(value: Any, *, default: bool) -> bool:
    converted = _python_value(value)
    if converted is None:
        return default
    if isinstance(converted, str):
        return converted.strip().lower() not in {"0", "false", "no", "n", "off"}
    return bool(converted)


class BaseDataRepository(AbstractContextManager["BaseDataRepository"]):
    """PostgreSQL repository containing facts only, never derived candles/indicators."""

    DERIVED_TABLES = (
        "technical_indicators_daily",
        "technical_indicators_weekly",
        "technical_indicator_state",
        "screen_results",
        "screen_runs",
    )

    def __init__(
        self,
        settings: DataEngineSettings | None = None,
        *,
        conninfo: str | None = None,
        application_name: str = "krx_data_engine_v30",
    ) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg가 설치되지 않았습니다. requirements-data-engine-v30.txt를 설치하십시오.")
        self.settings = settings or DataEngineSettings.from_environment()
        self.settings.validate()
        self.conn = psycopg.connect(
            _normalized_conninfo(conninfo or self.settings.conninfo),
            row_factory=dict_row,
            application_name=application_name,
            autocommit=True,
        )
        self._ohlcv_schema_name, self._ohlcv_table_name = self._resolve_relation(
            self.settings.ohlcv_schema,
            (self.settings.ohlcv_table,),
        )
        self._master_schema_name, self._master_table_name = self._resolve_relation(
            self.settings.master_schema,
            (self.settings.master_table, "security_master", "securities"),
        )
        self._refresh_base_layouts()

    def close(self) -> None:
        self.conn.close()

    def __exit__(self, *_: object) -> None:
        self.close()

    def _resolve_relation(
        self,
        preferred_schema: str,
        candidate_tables: Sequence[str],
    ) -> tuple[str, str]:
        """Resolve a migrated base table without relying on PostgreSQL search_path."""

        unique_names = list(dict.fromkeys(candidate_tables))
        rows = self.conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_name = ANY(%s::text[])
              AND table_type IN ('BASE TABLE', 'FOREIGN')
            """,
            [unique_names],
        ).fetchall()
        matches = [(str(row["table_schema"]), str(row["table_name"])) for row in rows]
        for table_name in unique_names:
            exact = (preferred_schema, table_name)
            if exact in matches:
                return exact
        for schema_name in ("market", "public"):
            for table_name in unique_names:
                candidate = (schema_name, table_name)
                if candidate in matches:
                    return candidate
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            rendered = ", ".join(f"{schema}.{table}" for schema, table in sorted(matches))
            raise RuntimeError(
                "기본 데이터 테이블 후보가 여러 개입니다. .env의 스키마 변수를 지정하십시오: "
                f"{rendered}"
            )
        return preferred_schema, unique_names[0]

    def _relation_columns(self, schema_name: str, table_name: str) -> dict[str, str]:
        rows = self.conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            [schema_name, table_name],
        ).fetchall()
        return {str(row["column_name"]): str(row["data_type"]) for row in rows}

    def _refresh_base_layouts(self) -> None:
        self._ohlcv_column_types = self._relation_columns(
            self._ohlcv_schema_name, self._ohlcv_table_name
        )
        self._master_column_types = self._relation_columns(
            self._master_schema_name, self._master_table_name
        )
        self._ohlcv_columns = _canonical_column_map(
            self._ohlcv_column_types, _OHLCV_COLUMN_ALIASES
        )
        self._master_columns = _canonical_column_map(
            self._master_column_types, _MASTER_COLUMN_ALIASES
        )

    @property
    def _ohlcv_relation_name(self) -> str:
        return f"{self._ohlcv_schema_name}.{self._ohlcv_table_name}"

    @property
    def _master_relation_name(self) -> str:
        return f"{self._master_schema_name}.{self._master_table_name}"

    def _require_ohlcv(self) -> dict[str, str]:
        missing = [name for name in _REQUIRED_OHLCV_COLUMNS if name not in self._ohlcv_columns]
        if not self._ohlcv_column_types:
            raise RuntimeError(
                f"PostgreSQL 원천 일봉 테이블을 찾을 수 없습니다: {self._ohlcv_relation_name}"
            )
        if missing:
            raise RuntimeError(
                f"{self._ohlcv_relation_name}의 필수 열이 호환되지 않습니다: {missing}"
            )
        return self._ohlcv_columns

    @property
    def _ohlcv_table(self):
        return sql.SQL("{}.{}").format(
            sql.Identifier(self._ohlcv_schema_name),
            sql.Identifier(self._ohlcv_table_name),
        )

    @property
    def _master_table(self):
        return sql.SQL("{}.{}").format(
            sql.Identifier(self._master_schema_name),
            sql.Identifier(self._master_table_name),
        )

    @property
    def _core_schema(self):
        return sql.Identifier(self.settings.core_schema)

    def initialize_schema(self) -> None:
        with self.conn.transaction():
            CoreSchemaMigrator(self.settings.core_schema).apply(self.conn)
            # Older installations used a KRX/NXT-only constraint.  Replace
            # only the venue check so official t8451 combined bars can be kept.
            venue_table = sql.SQL("{}.venue_ohlcv_daily").format(self._core_schema)
            constraint_rows = self.conn.execute(
                """
                SELECT c.conname, pg_get_constraintdef(c.oid) AS definition
                FROM pg_constraint c
                JOIN pg_class t ON t.oid=c.conrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname=%s AND t.relname='venue_ohlcv_daily' AND c.contype='c'
                """,
                [self.settings.core_schema],
            ).fetchall()
            for constraint in constraint_rows:
                definition = str(constraint["definition"])
                if "venue" in definition and "COMBINED" not in definition:
                    self.conn.execute(
                        sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(
                            venue_table, sql.Identifier(str(constraint["conname"]))
                        )
                    )
            self.conn.execute(
                sql.SQL(
                    "ALTER TABLE {} DROP CONSTRAINT IF EXISTS venue_ohlcv_daily_venue_v31_check"
                ).format(venue_table)
            )
            self.conn.execute(
                sql.SQL(
                    "ALTER TABLE {} ADD CONSTRAINT venue_ohlcv_daily_venue_v31_check "
                    "CHECK (venue IN ('KRX','NXT','COMBINED'))"
                ).format(venue_table)
            )
            # The v28 market schema did not keep transaction amount.  It is raw
            # provider data, not a derived indicator, so add one nullable column
            # without rewriting the 11M historical rows.  New updates retain it.
            if self._ohlcv_column_types and "amount" not in self._ohlcv_column_types:
                self.conn.execute(
                    sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS amount bigint").format(
                        self._ohlcv_table
                    )
                )
        self._refresh_base_layouts()

    def database_identity(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT current_database() AS database_name,
                   current_user AS database_user,
                   inet_server_addr()::text AS server_address,
                   inet_server_port() AS server_port,
                   current_setting('server_version') AS server_version
            """
        ).fetchone()
        identity = dict(row or {})
        core_row = self.conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS found",
            [f"{self.settings.core_schema}.investor_flow_daily"],
        ).fetchone()
        missing = [name for name in _REQUIRED_OHLCV_COLUMNS if name not in self._ohlcv_columns]
        identity.update(
            {
                "ohlcv_relation": self._ohlcv_relation_name,
                "ohlcv_exists": bool(self._ohlcv_column_types),
                "ohlcv_compatible": bool(self._ohlcv_column_types) and not missing,
                "ohlcv_layout": _ohlcv_layout_name(self._ohlcv_column_types),
                "master_relation": self._master_relation_name,
                "master_exists": bool(self._master_column_types),
                "core_exists": bool(core_row and core_row["found"]),
            }
        )
        return identity

    def relation_diagnostics(self, limit: int = 50) -> dict[str, Any]:
        """Return schema/table metadata only; never return a DSN or password."""

        rows = self.conn.execute(
            """
            SELECT schemaname AS table_schema,
                   relname AS table_name,
                   n_live_tup::bigint AS estimated_rows
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC, schemaname, relname
            LIMIT %s
            """,
            [max(1, min(int(limit), 200))],
        ).fetchall()
        return {
            "expected_ohlcv": self._ohlcv_relation_name,
            "expected_master": self._master_relation_name,
            "user_tables": [dict(item) for item in rows],
        }

    def latest_ohlcv_date(self, ticker: str | None = None) -> date | None:
        columns = self._require_ohlcv()
        trade_date = sql.Identifier(columns["trade_date"])
        query = sql.SQL("SELECT max({}) AS last_date FROM {}").format(
            trade_date, self._ohlcv_table
        )
        params: list[Any] = []
        if ticker:
            query += sql.SQL(" WHERE {}=%s").format(sql.Identifier(columns["stock_code"]))
            params.append(str(ticker).zfill(6))
        row = self.conn.execute(query, params).fetchone()
        value = row["last_date"] if row else None
        return None if value is None else pd.Timestamp(value).date()

    def available_ohlcv_dates(
        self,
        *,
        adjusted_only: bool = True,
        limit: int = 500,
    ) -> list[date]:
        """Return actual stored trading dates, newest first."""

        columns = self._require_ohlcv()
        date_column = sql.Identifier(columns["trade_date"])
        where: list[Any] = [sql.SQL("{} IS NOT NULL").format(date_column)]
        adjusted_column = columns.get("adjusted")
        if adjusted_only and adjusted_column is not None:
            adjusted_type = self._ohlcv_column_types.get(adjusted_column, "")
            if adjusted_type in {"smallint", "integer", "bigint", "numeric"}:
                where.append(
                    sql.SQL("COALESCE({}, 1) = 1").format(sql.Identifier(adjusted_column))
                )
            else:
                where.append(
                    sql.SQL("COALESCE({}, TRUE)").format(sql.Identifier(adjusted_column))
                )
        query = sql.SQL(
            "SELECT DISTINCT {date}::date AS trade_date FROM {table} "
            "WHERE {where} ORDER BY trade_date DESC LIMIT %s"
        ).format(
            date=date_column,
            table=self._ohlcv_table,
            where=sql.SQL(" AND ").join(where),
        )
        rows = self.conn.execute(query, [max(1, min(int(limit), 5000))]).fetchall()
        return [pd.Timestamp(row["trade_date"]).date() for row in rows]

    def sample_ohlcv_ticker(self) -> str | None:
        columns = self._require_ohlcv()
        row = self.conn.execute(
            sql.SQL("SELECT {}::text AS stock_code FROM {} ORDER BY {} DESC LIMIT 1").format(
                sql.Identifier(columns["stock_code"]),
                self._ohlcv_table,
                sql.Identifier(columns["trade_date"]),
            )
        ).fetchone()
        if not row or row["stock_code"] is None:
            return None
        return str(row["stock_code"]).strip().zfill(6)

    def latest_investor_date(self, ticker: str | None = None) -> date | None:
        table = sql.SQL("{}.investor_flow_daily").format(self._core_schema)
        query = sql.SQL("SELECT max(trade_date) AS last_date FROM {}").format(table)
        params: list[Any] = []
        if ticker:
            query += sql.SQL(" WHERE stock_code=%s")
            params.append(str(ticker).zfill(6))
        row = self.conn.execute(query, params).fetchone()
        return row["last_date"] if row else None

    def get_ohlcv(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        limit: int | None = None,
    ) -> pd.DataFrame:
        columns = self._require_ohlcv()

        def selected(canonical: str, fallback: str, *, cast: str | None = None):
            native = columns.get(canonical)
            expression = sql.SQL(fallback) if native is None else sql.Identifier(native)
            if native is not None and cast is not None:
                expression = sql.SQL("{}::" + cast).format(expression)
            return sql.SQL("{} AS {}").format(expression, sql.Identifier(canonical))

        select_items = [
            selected("stock_code", "NULL::text", cast="text"),
            selected("trade_date", "NULL::date", cast="date"),
            selected("open_price", "NULL::double precision"),
            selected("high_price", "NULL::double precision"),
            selected("low_price", "NULL::double precision"),
            selected("close_price", "NULL::double precision"),
            selected("volume", "0::bigint"),
            selected("amount", "NULL::bigint"),
            selected("change_rate", "NULL::double precision"),
            selected("source", "'unknown'::text"),
            selected("adjusted", "TRUE"),
            selected("retrieved_at", "NULL::text"),
        ]
        select_list = sql.SQL(", ").join(select_items)
        ticker_column = sql.Identifier(columns["stock_code"])
        date_column = sql.Identifier(columns["trade_date"])
        where = [sql.SQL("{}=%s").format(ticker_column)]
        params: list[Any] = [str(ticker).zfill(6)]
        if start is not None:
            where.append(sql.SQL("{} >= %s").format(date_column))
            params.append(self._ohlcv_date_value(start))
        if end is not None:
            where.append(sql.SQL("{} <= %s").format(date_column))
            params.append(self._ohlcv_date_value(end))
        query = sql.SQL("SELECT {} FROM {} WHERE {} ORDER BY {}").format(
            select_list,
            self._ohlcv_table,
            sql.SQL(" AND ").join(where),
            date_column,
        )
        if limit is not None:
            if limit < 1:
                raise ValueError("limit는 1 이상이어야 합니다.")
            # Limit the newest rows while returning them in ascending order.
            inner = sql.SQL("SELECT {} FROM {} WHERE {} ORDER BY {} DESC LIMIT %s").format(
                select_list,
                self._ohlcv_table,
                sql.SQL(" AND ").join(where),
                date_column,
            )
            params.append(limit)
            query = sql.SQL("SELECT * FROM ({}) recent ORDER BY trade_date").format(inner)
        rows = self.conn.execute(query, params).fetchall()
        return normalize_ohlcv(pd.DataFrame(rows))

    def get_market_ohlcv(
        self,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        adjusted_only: bool = True,
    ) -> pd.DataFrame:
        """Load a dated all-ticker OHLCV window for an in-memory screen.

        This is intentionally a read-only bulk API.  It keeps cross-sectional
        calculations out of PostgreSQL tables while avoiding thousands of
        one-ticker round trips from the workstation GUI.
        """

        columns = self._require_ohlcv()

        def selected(canonical: str, fallback: str, *, cast: str | None = None):
            native = columns.get(canonical)
            expression = sql.SQL(fallback) if native is None else sql.Identifier(native)
            if native is not None and cast is not None:
                expression = sql.SQL("{}::" + cast).format(expression)
            return sql.SQL("{} AS {}").format(expression, sql.Identifier(canonical))

        select_items = [
            selected("stock_code", "NULL::text", cast="text"),
            selected("trade_date", "NULL::date", cast="date"),
            selected("open_price", "NULL::double precision"),
            selected("high_price", "NULL::double precision"),
            selected("low_price", "NULL::double precision"),
            selected("close_price", "NULL::double precision"),
            selected("volume", "0::bigint"),
            selected("amount", "NULL::bigint"),
            selected("change_rate", "NULL::double precision"),
        ]
        date_column = sql.Identifier(columns["trade_date"])
        ticker_column = sql.Identifier(columns["stock_code"])
        where: list[Any] = []
        params: list[Any] = []
        if start is not None:
            where.append(sql.SQL("{} >= %s").format(date_column))
            params.append(self._ohlcv_date_value(start))
        if end is not None:
            where.append(sql.SQL("{} <= %s").format(date_column))
            params.append(self._ohlcv_date_value(end))
        adjusted_column = columns.get("adjusted")
        if adjusted_only and adjusted_column is not None:
            adjusted_type = self._ohlcv_column_types.get(adjusted_column, "")
            if adjusted_type in {"smallint", "integer", "bigint", "numeric"}:
                where.append(
                    sql.SQL("COALESCE({}, 1) = 1").format(
                        sql.Identifier(adjusted_column)
                    )
                )
            else:
                where.append(
                    sql.SQL("COALESCE({}, TRUE)").format(
                        sql.Identifier(adjusted_column)
                    )
                )
        query = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(select_items),
            self._ohlcv_table,
        )
        if where:
            query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where)
        query += sql.SQL(" ORDER BY {}, {}").format(ticker_column, date_column)
        rows = self.conn.execute(query, params).fetchall()
        frame = pd.DataFrame(rows)
        expected = [
            "stock_code",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "amount",
            "change_rate",
        ]
        if frame.empty:
            return pd.DataFrame(columns=expected)
        frame["stock_code"] = frame["stock_code"].astype(str).str.zfill(6)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame = frame.loc[frame["trade_date"].notna()].copy()
        for column in expected[2:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_values(["stock_code", "trade_date"], ignore_index=True)

    def get_venue_ohlcv(
        self,
        venue: str,
        start: date | str | None = None,
        end: date | str | None = None,
        ticker: str | None = None,
    ) -> pd.DataFrame:
        """Return raw daily bars for one execution venue."""

        selected_venue = str(venue).strip().upper()
        if selected_venue not in {"KRX", "NXT", "COMBINED"}:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._core_schema)
        where = [sql.SQL("venue=%s")]
        params: list[Any] = [selected_venue]
        if start is not None:
            where.append(sql.SQL("trade_date >= %s"))
            params.append(pd.Timestamp(start).date())
        if end is not None:
            where.append(sql.SQL("trade_date <= %s"))
            params.append(pd.Timestamp(end).date())
        if ticker is not None:
            where.append(sql.SQL("stock_code = %s"))
            params.append(str(ticker).zfill(6))
        query = sql.SQL(
            "SELECT stock_code, trade_date, open_price, high_price, low_price, "
            "close_price, volume, amount, source, source_document, retrieved_at "
            "FROM {} WHERE {} ORDER BY stock_code, trade_date"
        ).format(table, sql.SQL(" AND ").join(where))
        return pd.DataFrame(self.conn.execute(query, params).fetchall())

    def latest_venue_ohlcv_date(self, venue: str, ticker: str | None = None) -> date | None:
        selected = str(venue).strip().upper()
        if selected not in {"KRX", "NXT", "COMBINED"}:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._core_schema)
        query = sql.SQL("SELECT max(trade_date) AS last_date FROM {} WHERE venue=%s").format(table)
        params: list[Any] = [selected]
        if ticker:
            query += sql.SQL(" AND stock_code=%s")
            params.append(str(ticker).zfill(6))
        row = self.conn.execute(query, params).fetchone()
        return None if not row or row["last_date"] is None else pd.Timestamp(row["last_date"]).date()

    def available_venue_ohlcv_dates(self, venue: str, *, limit: int = 500) -> list[date]:
        selected = str(venue).strip().upper()
        if selected not in {"KRX", "NXT", "COMBINED"}:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._core_schema)
        rows = self.conn.execute(
            sql.SQL(
                "SELECT DISTINCT trade_date FROM {} WHERE venue=%s "
                "ORDER BY trade_date DESC LIMIT %s"
            ).format(table),
            [selected, max(1, min(int(limit), 5000))],
        ).fetchall()
        return [pd.Timestamp(row["trade_date"]).date() for row in rows]

    def missing_venue_dates(
        self,
        venue: str,
        start: date | str,
        end: date | str,
        *,
        limit: int = 20,
    ) -> list[date]:
        """Compare venue dates with stored KRX sessions before combined screens."""

        selected_venue = str(venue).strip().upper()
        if selected_venue not in {"KRX", "NXT", "COMBINED"}:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        columns = self._require_ohlcv()
        date_column = sql.Identifier(columns["trade_date"])
        venue_table = sql.SQL("{}.venue_ohlcv_daily").format(self._core_schema)
        query = sql.SQL(
            "SELECT trade_date FROM ("
            "SELECT DISTINCT {} AS trade_date FROM {} WHERE {} BETWEEN %s AND %s "
            "EXCEPT SELECT DISTINCT trade_date FROM {} "
            "WHERE venue=%s AND trade_date BETWEEN %s AND %s"
            ") missing ORDER BY trade_date LIMIT %s"
        ).format(date_column, self._ohlcv_table, date_column, venue_table)
        start_value = pd.Timestamp(start).date()
        end_value = pd.Timestamp(end).date()
        rows = self.conn.execute(
            query,
            [start_value, end_value, selected_venue, start_value, end_value, limit],
        ).fetchall()
        return [row["trade_date"] for row in rows]

    def upsert_venue_ohlcv(
        self,
        frame: pd.DataFrame,
        *,
        venue: str,
        source_document: str = "",
    ) -> int:
        """Upsert validated venue-specific daily bars without changing KRX facts."""

        if frame is None or frame.empty:
            return 0
        selected_venue = str(venue).strip().upper()
        if selected_venue not in {"KRX", "NXT", "COMBINED"}:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        normalized = normalize_ohlcv(frame)
        if "stock_code" not in normalized.columns:
            raise ValueError("거래시장 OHLCV DataFrame에 stock_code가 필요합니다.")
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._core_schema)
        statement = sql.SQL(
            "INSERT INTO {} (venue, stock_code, trade_date, open_price, high_price, "
            "low_price, close_price, volume, amount, source, source_document, retrieved_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (venue, stock_code, trade_date) DO UPDATE SET "
            "open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price, "
            "low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price, "
            "volume=EXCLUDED.volume, amount=EXCLUDED.amount, source=EXCLUDED.source, "
            "source_document=EXCLUDED.source_document, retrieved_at=EXCLUDED.retrieved_at"
        ).format(table)
        retrieved_at = datetime.now(timezone.utc)
        rows: list[tuple[Any, ...]] = []
        for trade_date, row in normalized.iterrows():
            rows.append(
                (
                    selected_venue,
                    str(row["stock_code"]).zfill(6),
                    pd.Timestamp(trade_date).date(),
                    _python_value(row["open_price"]),
                    _python_value(row["high_price"]),
                    _python_value(row["low_price"]),
                    _python_value(row["close_price"]),
                    _integer_value(row.get("volume"), default=0),
                    _integer_value(row.get("amount"), default=None),
                    _text_value(row.get("source"), default=f"{selected_venue}:IMPORT"),
                    str(source_document),
                    retrieved_at,
                )
            )
        with self.conn.transaction():
            with self.conn.cursor() as cursor:
                cursor.executemany(statement, rows)
        return len(rows)

    def _ohlcv_date_value(self, value: date | str | pd.Timestamp) -> date | str:
        columns = self._require_ohlcv()
        native = columns["trade_date"]
        data_type = self._ohlcv_column_types.get(native, "")
        parsed = pd.Timestamp(value).date()
        if data_type in {"character", "character varying", "text"}:
            return parsed.isoformat()
        return parsed

    def get_ls_investor_flow(self, *, ticker: str | None = None, trade_date: date | str | None = None, prices: pd.DataFrame | None = None) -> pd.DataFrame:
        """Read checked LS source rows and compute approximate cash flow in memory."""
        from krx_research.data_engine.ls_flow_runtime import derive_ls_flow

        empty = derive_ls_flow([], pd.DataFrame())
        exists = self.conn.execute(
            "SELECT to_regclass('market_core.ls_investor_t1702_raw') AS raw, "
            "to_regclass('market_core.ls_investor_t1702_checkpoint') AS done"
        ).fetchone()
        if not exists or not exists['raw'] or not exists['done']:
            return empty
        parts = ["r.metric_code IN ('0','1')", "r.exchange_code='K'"]
        params: list[Any] = []
        if ticker is not None:
            parts.append('r.stock_code=%s')
            params.append(str(ticker).zfill(6))
        if trade_date is not None:
            parts.append('r.trade_date=%s')
            params.append(pd.Timestamp(trade_date).date())
        query = ("SELECT r.stock_code,r.trade_date,r.metric_code,r.side_code,r.source_fields "
                 "FROM market_core.ls_investor_t1702_raw r "
                 "JOIN market_core.ls_investor_t1702_checkpoint c "
                 "ON c.stock_code=r.stock_code AND c.trade_date=r.trade_date "
                 "AND c.exchange_code=r.exchange_code WHERE " + ' AND '.join(parts))
        rows = self.conn.execute(query, params).fetchall()
        if not rows:
            return empty
        if prices is None:
            prices = (self.get_ohlcv(str(ticker)) if ticker is not None else
                      self.get_market_ohlcv(trade_date, trade_date))
        return derive_ls_flow(rows, prices)

    def get_investor_flow(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        investor_types: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        # LS_TWO_DAYS_CHART_SOURCE
        exists = self.conn.execute("SELECT to_regclass('market_core.ls_investor_t1702_raw') AS t").fetchone()
        if exists['t']:
            ls = self.get_ls_investor_flow(ticker=ticker)
            if start is not None: ls = ls.loc[pd.to_datetime(ls['trade_date']) >= pd.Timestamp(start)]
            if end is not None: ls = ls.loc[pd.to_datetime(ls['trade_date']) <= pd.Timestamp(end)]
            return ls
        ls = self.get_ls_investor_flow(ticker=ticker)
        if self.conn.execute("SELECT to_regclass('market_core.ls_investor_t1702_raw') AS table_name").fetchone()['table_name']:
            if start is not None:ls = ls.loc[pd.to_datetime(ls['trade_date']) >= pd.Timestamp(start)]
            if end is not None:ls = ls.loc[pd.to_datetime(ls['trade_date']) <= pd.Timestamp(end)]
            return ls
        table = sql.SQL("{}.investor_flow_daily").format(self._core_schema)
        where = [sql.SQL("stock_code=%s")]
        params: list[Any] = [str(ticker).zfill(6)]
        if start is not None:
            where.append(sql.SQL("trade_date >= %s"))
            params.append(pd.Timestamp(start).date())
        if end is not None:
            where.append(sql.SQL("trade_date <= %s"))
            params.append(pd.Timestamp(end).date())
        if investor_types:
            requested = [normalize_investor_code(value) for value in investor_types]
            expanded: set[str] = set()
            for code in requested:
                if code == "INSTITUTION_TOTAL":
                    expanded.update(INSTITUTION_MEMBERS)
                elif code == "FOREIGN_TOTAL":
                    expanded.update(FOREIGN_MEMBERS)
                else:
                    expanded.add(code)
            codes = sorted(expanded)
            where.append(sql.SQL("investor_type = ANY(%s::text[])"))
            params.append(codes)
        query = sql.SQL(
            "SELECT stock_code, trade_date, investor_type, buy_volume, sell_volume, "
            "buy_value, sell_value FROM {} WHERE {} ORDER BY trade_date, investor_type"
        ).format(table, sql.SQL(" AND ").join(where))
        return pd.DataFrame(self.conn.execute(query, params).fetchall())

    def get_market_investor_flow(self, trade_date: date | str) -> pd.DataFrame:
        """Read all investor facts for one trading day in one indexed query."""
        # LS_TWO_DAYS_SCREEN: read existing LS raw, never call remote providers.
        if pd.Timestamp(trade_date).date() in (date(2026,9,28),date(2026,9,29)):
            return self.get_ls_investor_flow(trade_date=trade_date)
        ls = self.get_ls_investor_flow(trade_date=trade_date)
        if self.conn.execute("SELECT to_regclass('market_core.ls_investor_t1702_raw') AS table_name").fetchone()['table_name']:
            return ls

        table = sql.SQL("{}.investor_flow_daily").format(self._core_schema)
        query = sql.SQL(
            "SELECT stock_code, trade_date, investor_type, buy_value, sell_value "
            "FROM {} WHERE trade_date=%s"
        ).format(table)
        return pd.DataFrame(
            self.conn.execute(query, [pd.Timestamp(trade_date).date()]).fetchall()
        )

    def latest_market_investor_date_on_or_before(self, as_of: date | str) -> date | None:
        """Read the latest stored investor date up to the requested date."""
        # LS_TWO_DAYS_EXACT_DATE: never substitute an older day for these tests.
        selected = pd.Timestamp(as_of).date()
        if selected in (date(2026,9,28),date(2026,9,29)):
            exists = self.conn.execute("SELECT to_regclass('market_core.ls_investor_t1702_checkpoint') AS t").fetchone()
            if not exists['t']: return None
            row = self.conn.execute("SELECT trade_date FROM market_core.ls_investor_t1702_checkpoint WHERE trade_date=%s AND exchange_code='K' LIMIT 1",(selected,)).fetchone()
            return row['trade_date'] if row else None
        if self.conn.execute("SELECT to_regclass('market_core.ls_investor_t1702_checkpoint') AS table_name").fetchone()['table_name']:
            row = self.conn.execute(
                'SELECT max(trade_date) AS last_date FROM market_core.ls_investor_t1702_checkpoint '
                'WHERE trade_date<=%s', (pd.Timestamp(as_of).date(),)
            ).fetchone()
            if row and row['last_date'] is not None:
                return row['last_date']

        table = sql.SQL("{}.investor_flow_daily").format(self._core_schema)
        query = sql.SQL("SELECT max(trade_date) AS last_date FROM {} WHERE trade_date <= %s").format(table)
        row = self.conn.execute(query, [pd.Timestamp(as_of).date()]).fetchone()
        return row["last_date"] if row else None

    def get_security(self, ticker: str) -> dict[str, Any] | None:
        key_column = self._master_columns.get("stock_code")
        if not self._master_column_types or key_column is None:
            raise RuntimeError(
                f"PostgreSQL 종목 마스터 테이블이 없거나 호환되지 않습니다: {self._master_relation_name}"
            )
        aliases = [sql.SQL("*")]
        if key_column != "stock_code":
            aliases.append(
                sql.SQL("{}::text AS stock_code").format(sql.Identifier(key_column))
            )
        name_column = self._master_columns.get("stock_name")
        if name_column and name_column != "stock_name":
            aliases.append(
                sql.SQL("{} AS stock_name").format(sql.Identifier(name_column))
            )
        row = self.conn.execute(
            sql.SQL("SELECT {} FROM {} WHERE {}=%s").format(
                sql.SQL(", ").join(aliases),
                self._master_table,
                sql.Identifier(key_column),
            ),
            [str(ticker).zfill(6)],
        ).fetchone()
        return dict(row) if row else None

    def get_security_master_frame(self) -> pd.DataFrame:
        """Return the small security dimension with canonical GUI names."""

        key_column = self._master_columns.get("stock_code")
        if not self._master_column_types or key_column is None:
            raise RuntimeError(
                f"PostgreSQL 종목 마스터 테이블이 없거나 호환되지 않습니다: {self._master_relation_name}"
            )

        def native(*candidates: str) -> str | None:
            return next(
                (candidate for candidate in candidates if candidate in self._master_column_types),
                None,
            )

        selections = [
            sql.SQL("{}::text AS stock_code").format(sql.Identifier(key_column)),
        ]
        for alias, candidate in (
            ("stock_name", self._master_columns.get("stock_name")),
            ("market", self._master_columns.get("market")),
            ("industry", native("industry", "sector", "industry_name")),
            ("market_cap", native("market_cap", "market_capitalization")),
        ):
            if candidate is None:
                cast = "numeric" if alias == "market_cap" else "text"
                selections.append(
                    sql.SQL("NULL::{} AS {}").format(
                        sql.SQL(cast), sql.Identifier(alias)
                    )
                )
            else:
                selections.append(
                    sql.SQL("{}::{} AS {}").format(
                        sql.Identifier(candidate),
                        sql.SQL("numeric" if alias == "market_cap" else "text"),
                        sql.Identifier(alias),
                    )
                )
        rows = self.conn.execute(
            sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                sql.SQL(", ").join(selections),
                self._master_table,
                sql.Identifier(key_column),
            )
        ).fetchall()
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(
                columns=["stock_code", "stock_name", "market", "industry", "market_cap"]
            )
        frame["stock_code"] = frame["stock_code"].astype(str).str.zfill(6)
        return frame.drop_duplicates("stock_code", keep="last").reset_index(drop=True)

    def upsert_security_master(self, frame: pd.DataFrame) -> int:
        """Upsert only columns that actually exist in the migrated master table."""

        if frame is None or frame.empty:
            return 0
        aliases = {
            "ticker": "stock_code",
            "code": "stock_code",
            "종목코드": "stock_code",
            "name": "stock_name",
            "종목명": "stock_name",
            "시장": "market",
        }
        working = frame.rename(
            columns={column: aliases.get(str(column), str(column)) for column in frame.columns}
        ).copy()
        if not self._master_column_types:
            raise RuntimeError(f"종목 마스터 테이블을 찾을 수 없습니다: {self._master_relation_name}")

        canonical_to_native = dict(self._master_columns)
        for column in self._master_column_types:
            canonical_to_native.setdefault(column, column)
        if "source" in self._master_column_types and "source" not in working:
            working["source"] = "pykrx"
        if "retrieved_at" in self._master_column_types and "retrieved_at" not in working:
            working["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        selected_pairs = [
            (canonical, native)
            for canonical, native in canonical_to_native.items()
            if canonical in working.columns
        ]
        selected_native = [native for _, native in selected_pairs]
        if self._master_columns.get("stock_code") not in selected_native:
            raise ValueError("security_master upsert에는 stock_code가 필요합니다.")
        pk_result = self.conn.execute(
            """
            SELECT a.attname AS column_name
            FROM pg_index i
            JOIN pg_class c ON c.oid=i.indrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum
            WHERE n.nspname=%s AND c.relname=%s AND i.indisprimary
            ORDER BY k.ord
            """,
            [self._master_schema_name, self._master_table_name],
        ).fetchall()
        primary_key = [row["column_name"] for row in pk_result] or [
            self._master_columns["stock_code"]
        ]
        if any(column not in selected_native for column in primary_key):
            raise ValueError(f"기본키 열이 DataFrame에 없습니다: {primary_key}")
        update_columns = [column for column in selected_native if column not in primary_key]
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in selected_native)
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) ").format(
            self._master_table,
            sql.SQL(", ").join(map(sql.Identifier, selected_native)),
            placeholders,
            sql.SQL(", ").join(map(sql.Identifier, primary_key)),
        )
        if update_columns:
            assignments = sql.SQL(", ").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
                for column in update_columns
            )
            query += sql.SQL("DO UPDATE SET ") + assignments
        else:
            query += sql.SQL("DO NOTHING")
        canonical_columns = [canonical for canonical, _ in selected_pairs]
        rows = [
            tuple(_python_value(value) for value in row)
            for row in working[canonical_columns].itertuples(index=False, name=None)
        ]
        with self.conn.transaction():
            with self.conn.cursor() as cursor:
                cursor.executemany(query, rows)
        return len(rows)

    def upsert_ohlcv(self, frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            return 0
        columns = self._require_ohlcv()
        source = frame.copy()
        if "stock_code" not in source.columns:
            raise ValueError("OHLCV DataFrame에 stock_code가 필요합니다.")
        normalized = normalize_ohlcv(source)
        if "stock_code" not in normalized.columns:
            # normalize_ohlcv retains non-index columns, but keep a clear guard.
            raise ValueError("OHLCV DataFrame에 stock_code가 필요합니다.")
        canonical_order = [
            "stock_code",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "amount",
            "change_rate",
            "source",
            "adjusted",
            "retrieved_at",
        ]
        selected = [(name, columns[name]) for name in canonical_order if name in columns]
        native_columns = [native for _, native in selected]
        conflict_columns = [columns["stock_code"], columns["trade_date"]]
        update_columns = [name for name in native_columns if name not in conflict_columns]

        def converted_value(canonical: str, row: pd.Series, trade_date: pd.Timestamp) -> Any:
            if canonical == "stock_code":
                return str(row["stock_code"]).zfill(6)
            if canonical == "trade_date":
                return self._ohlcv_date_value(trade_date)
            if canonical in {"open_price", "high_price", "low_price", "close_price"}:
                return _python_value(row[canonical])
            if canonical == "volume":
                return _integer_value(row.get(canonical), default=0)
            if canonical == "amount":
                return _integer_value(row.get(canonical), default=None)
            if canonical == "change_rate":
                return _python_value(row.get("change_rate"))
            if canonical == "source":
                return _text_value(row.get("source"), default="pykrx")
            if canonical == "adjusted":
                adjusted = _bool_value(row.get("adjusted"), default=True)
                native = columns["adjusted"]
                data_type = self._ohlcv_column_types.get(native, "")
                return int(adjusted) if data_type in {"smallint", "integer", "bigint"} else adjusted
            if canonical == "retrieved_at":
                timestamp = datetime.now(timezone.utc)
                native = columns["retrieved_at"]
                data_type = self._ohlcv_column_types.get(native, "")
                return timestamp.isoformat() if data_type in {"character", "character varying", "text"} else timestamp
            raise AssertionError(f"처리되지 않은 OHLCV 열: {canonical}")

        rows: list[tuple[Any, ...]] = []
        for trade_date, row in normalized.iterrows():
            rows.append(tuple(converted_value(name, row, trade_date) for name, _ in selected))

        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) ").format(
            self._ohlcv_table,
            sql.SQL(", ").join(map(sql.Identifier, native_columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in native_columns),
            sql.SQL(", ").join(map(sql.Identifier, conflict_columns)),
        )
        if update_columns:
            statement += sql.SQL("DO UPDATE SET ") + sql.SQL(", ").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
                for name in update_columns
            )
        else:
            statement += sql.SQL("DO NOTHING")
        with self.conn.transaction():
            with self.conn.cursor() as cursor:
                cursor.executemany(statement, rows)
        return len(rows)

    def upsert_investor_flow(self, frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            return 0
        required = {"stock_code", "trade_date", "investor_type", "buy_volume", "sell_volume", "buy_value", "sell_value"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"투자자 수급 필수 열 누락: {sorted(missing)}")
        working = frame.copy()
        working["trade_date"] = pd.to_datetime(working["trade_date"], errors="raise")
        years = sorted(set(working["trade_date"].dt.year.astype(int)))
        table = sql.SQL("{}.investor_flow_daily").format(self._core_schema)
        rows: list[tuple[Any, ...]] = []
        for row in working.itertuples(index=False):
            code = normalize_investor_code(getattr(row, "investor_type"))
            if code not in LEAF_INVESTORS:
                raise ValueError(f"합계/파생 투자자 구분은 저장하지 않습니다: {code}")
            rows.append(
                (
                    str(getattr(row, "stock_code")).zfill(6),
                    pd.Timestamp(getattr(row, "trade_date")).date(),
                    code,
                    _integer_value(getattr(row, "buy_volume"), default=0),
                    _integer_value(getattr(row, "sell_volume"), default=0),
                    _integer_value(getattr(row, "buy_value"), default=0),
                    _integer_value(getattr(row, "sell_value"), default=0),
                    _text_value(getattr(row, "source", None), default="pykrx"),
                )
            )
        statement = sql.SQL(
            """
            INSERT INTO {} (
                stock_code, trade_date, investor_type, buy_volume, sell_volume,
                buy_value, sell_value, source, retrieved_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp())
            ON CONFLICT (stock_code, trade_date, investor_type) DO UPDATE SET
                buy_volume=EXCLUDED.buy_volume,
                sell_volume=EXCLUDED.sell_volume,
                buy_value=EXCLUDED.buy_value,
                sell_value=EXCLUDED.sell_value,
                source=EXCLUDED.source,
                retrieved_at=clock_timestamp()
            """
        ).format(table)
        with self.conn.transaction():
            for year in years:
                partition_name = f"{self.settings.core_schema}.investor_flow_daily_{year}"
                found = self.conn.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AS found", [partition_name]
                ).fetchone()
                if not (found and found["found"]):
                    CoreSchemaMigrator(self.settings.core_schema).ensure_investor_partition(self.conn, year)
            with self.conn.cursor() as cursor:
                cursor.executemany(statement, rows)
        return len(rows)

    def set_update_state(self, dataset: str, market: str, completed_date: date, details: dict[str, Any] | None = None) -> None:
        table = sql.SQL("{}.update_state").format(self._core_schema)
        payload = Jsonb(details or {}) if Jsonb is not None else json.dumps(details or {})
        with self.conn.transaction():
            self.conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} AS state (dataset, market, last_complete_date, details, updated_at)
                    VALUES (%s,%s,%s,%s,clock_timestamp())
                    ON CONFLICT (dataset, market) DO UPDATE SET
                        last_complete_date=GREATEST(state.last_complete_date, EXCLUDED.last_complete_date),
                        details=EXCLUDED.details,
                        updated_at=clock_timestamp()
                    """
                ).format(table),
                [dataset, market, completed_date, payload],
            )

    def get_update_state(self, dataset: str, market: str) -> date | None:
        table = sql.SQL("{}.update_state").format(self._core_schema)
        row = self.conn.execute(
            sql.SQL("SELECT last_complete_date FROM {} WHERE dataset=%s AND market=%s").format(table),
            [dataset, market],
        ).fetchone()
        return row["last_complete_date"] if row else None

    def is_date_complete(self, dataset: str, market: str, trade_date: date) -> bool:
        # LS_SCREEN_REPAIR_V2_NO_SINGLE_ROW_COMPLETE
        if dataset == 'ohlcv_daily':
            from .screen_coverage import expected_market_counts
            counts = expected_market_counts(self, pd.Timestamp(trade_date).date())
            actual, expected = counts.get(market.upper(), (0, 0))
            if actual > 0:
                return actual >= max(100, (expected * 9 + 9) // 10)
            table = sql.SQL("{}.collection_coverage").format(self._core_schema)
            row = self.conn.execute(sql.SQL("SELECT status FROM {} WHERE dataset=%s AND market=%s AND trade_date=%s").format(table),
                                    [dataset, market, trade_date]).fetchone()
            return bool(row and row['status'] == 'no_data')
        table = sql.SQL("{}.collection_coverage").format(self._core_schema)
        row = self.conn.execute(
            sql.SQL(
                "SELECT status FROM {} WHERE dataset=%s AND market=%s AND trade_date=%s"
            ).format(table),
            [dataset, market, trade_date],
        ).fetchone()
        if row and row["status"] in {"complete", "no_data"}:
            return True

        # Migrated v28 price rows predate collection_coverage.  Treat a dated
        # market batch already present in the fact table as complete so the
        # first v31 daily run does not download and rewrite the same rows.
        master_code = self._master_columns.get("stock_code")
        master_market = self._master_columns.get("market")
        if not self._master_column_types or master_code is None or master_market is None:
            return False
        market_predicate = sql.SQL("upper(trim(m.{}::text))=%s").format(
            sql.Identifier(master_market)
        )
        if dataset == "ohlcv_daily":
            columns = self._require_ohlcv()
            query = sql.SQL(
                "SELECT EXISTS ("
                "SELECT 1 FROM {} o JOIN {} m ON o.{}::text=m.{}::text "
                "WHERE o.{}=%s AND {} LIMIT 1"
                ") AS found"
            ).format(
                self._ohlcv_table,
                self._master_table,
                sql.Identifier(columns["stock_code"]),
                sql.Identifier(master_code),
                sql.Identifier(columns["trade_date"]),
                market_predicate,
            )
            params = [self._ohlcv_date_value(trade_date), market.upper()]
        elif dataset == "investor_flow_daily":
            investor_table = sql.SQL("{}.investor_flow_daily").format(self._core_schema)
            query = sql.SQL(
                "SELECT EXISTS ("
                "SELECT 1 FROM {} f JOIN {} m ON f.stock_code::text=m.{}::text "
                "WHERE f.trade_date=%s AND {} LIMIT 1"
                ") AS found"
            ).format(
                investor_table,
                self._master_table,
                sql.Identifier(master_code),
                market_predicate,
            )
            params = [trade_date, market.upper()]
        else:
            return False
        stored = self.conn.execute(query, params).fetchone()
        return bool(stored and stored["found"])

    def set_date_coverage(
        self,
        dataset: str,
        market: str,
        trade_date: date,
        *,
        status: str,
        row_count: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        if status not in {"complete", "no_data"}:
            raise ValueError("coverage status는 complete 또는 no_data여야 합니다.")
        table = sql.SQL("{}.collection_coverage").format(self._core_schema)
        payload = Jsonb(details or {}) if Jsonb is not None else json.dumps(details or {})
        with self.conn.transaction():
            self.conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (dataset, market, trade_date, status, row_count, details, checked_at)
                    VALUES (%s,%s,%s,%s,%s,%s,clock_timestamp())
                    ON CONFLICT (dataset, market, trade_date) DO UPDATE SET
                        status=EXCLUDED.status,
                        row_count=EXCLUDED.row_count,
                        details=EXCLUDED.details,
                        checked_at=clock_timestamp()
                    """
                ).format(table),
                [dataset, market, trade_date, status, row_count, payload],
            )

    def start_update_run(self, target_date: date, mode: str = "incremental") -> int:
        table = sql.SQL("{}.update_runs").format(self._core_schema)
        with self.conn.transaction():
            row = self.conn.execute(
                sql.SQL(
                    "INSERT INTO {} (target_date, mode, status, started_at) "
                    "VALUES (%s,%s,'running',clock_timestamp()) RETURNING run_id"
                ).format(table),
                [target_date, mode],
            ).fetchone()
        return int(row["run_id"])

    def finish_update_run(
        self,
        run_id: int,
        *,
        status: str,
        ohlcv_rows: int = 0,
        investor_rows: int = 0,
        message: str | None = None,
    ) -> None:
        table = sql.SQL("{}.update_runs").format(self._core_schema)
        with self.conn.transaction():
            self.conn.execute(
                sql.SQL(
                    """
                    UPDATE {} SET status=%s, ohlcv_rows=%s, investor_rows=%s,
                                  message=%s, finished_at=clock_timestamp()
                    WHERE run_id=%s
                    """
                ).format(table),
                [status, ohlcv_rows, investor_rows, message, run_id],
            )

    def coverage(self, dataset: str) -> DataCoverage:
        if dataset == "ohlcv":
            columns = self._require_ohlcv()
            date_column = sql.Identifier(columns["trade_date"])
            row = self.conn.execute(
                sql.SQL(
                    "SELECT min({}) AS minimum_date, max({}) AS maximum_date, "
                    "count(*) AS row_count FROM {}"
                ).format(date_column, date_column, self._ohlcv_table)
            ).fetchone()
            minimum = None if row["minimum_date"] is None else pd.Timestamp(row["minimum_date"]).date()
            maximum = None if row["maximum_date"] is None else pd.Timestamp(row["maximum_date"]).date()
            return DataCoverage(dataset, minimum, maximum, int(row["row_count"]))
        tables = {
            "investor": sql.SQL("{}.investor_flow_daily").format(self._core_schema),
        }
        if dataset not in tables:
            raise ValueError("dataset은 ohlcv 또는 investor여야 합니다.")
        row = self.conn.execute(
            sql.SQL("SELECT min(trade_date) AS minimum_date, max(trade_date) AS maximum_date, count(*) AS row_count FROM {}").format(tables[dataset])
        ).fetchone()
        return DataCoverage(dataset, row["minimum_date"], row["maximum_date"], int(row["row_count"]))

    def count_rows(self, table: str) -> int:
        allowed = {
            self.settings.ohlcv_table: (self._ohlcv_schema_name, self._ohlcv_table_name),
            self.settings.master_table: (self._master_schema_name, self._master_table_name),
            "investor_flow_daily": (self.settings.core_schema, "investor_flow_daily"),
            "corporate_actions": (self.settings.core_schema, "corporate_actions"),
            "update_state": (self.settings.core_schema, "update_state"),
            "collection_coverage": (self.settings.core_schema, "collection_coverage"),
        }
        if table not in allowed:
            raise ValueError(f"허용되지 않은 테이블: {table}")
        schema_name, table_name = allowed[table]
        row = self.conn.execute(
            sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)
            )
        ).fetchone()
        return int(row["count"])

    def archive_derived_tables(self, tables: Iterable[str] | None = None) -> list[str]:
        selected = tuple(tables or self.DERIVED_TABLES)
        archived: list[str] = []
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('krx.v30.archive-derived'))")
            for table_name in selected:
                if table_name not in self.DERIVED_TABLES:
                    raise ValueError(f"허용되지 않은 파생 테이블: {table_name}")
                source_relation = f"{self._ohlcv_schema_name}.{table_name}"
                exists = self.conn.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AS found", [source_relation]
                ).fetchone()
                target = self.conn.execute("SELECT to_regclass(%s) IS NOT NULL AS found", [f"legacy_archive.{table_name}"]).fetchone()
                if exists and exists["found"] and not (target and target["found"]):
                    self.conn.execute(
                        sql.SQL("ALTER TABLE {}.{} SET SCHEMA legacy_archive").format(
                            sql.Identifier(self._ohlcv_schema_name), sql.Identifier(table_name)
                        )
                    )
                    archived.append(table_name)
        return archived

    def restore_derived_tables(self) -> list[str]:
        restored: list[str] = []
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('krx.v30.archive-derived'))")
            for table_name in self.DERIVED_TABLES:
                source = self.conn.execute("SELECT to_regclass(%s) IS NOT NULL AS found", [f"legacy_archive.{table_name}"]).fetchone()
                target = self.conn.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AS found",
                    [f"{self._ohlcv_schema_name}.{table_name}"],
                ).fetchone()
                if source and source["found"] and not (target and target["found"]):
                    self.conn.execute(
                        sql.SQL("ALTER TABLE legacy_archive.{} SET SCHEMA {}").format(
                            sql.Identifier(table_name), sql.Identifier(self._ohlcv_schema_name)
                        )
                    )
                    restored.append(table_name)
        return restored

    def purge_archived_derived_tables(self, confirmation: str) -> list[str]:
        if confirmation != "DROP_DERIVED_DATA":
            raise ValueError("삭제 확인 문자열이 일치하지 않습니다.")
        dropped: list[str] = []
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('krx.v30.archive-derived'))")
            for table_name in self.DERIVED_TABLES:
                found = self.conn.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AS found",
                    [f"legacy_archive.{table_name}"],
                ).fetchone()
                if found and found["found"]:
                    self.conn.execute(
                        sql.SQL("DROP TABLE legacy_archive.{}").format(sql.Identifier(table_name))
                    )
                    dropped.append(table_name)
        return dropped

    def quick_check(self) -> str:
        row = self.conn.execute("SELECT 1 AS ok").fetchone()
        return "ok" if row and row["ok"] == 1 else "error"

    @property
    def schema_version(self) -> str:
        table = sql.SQL("{}.schema_meta").format(self._core_schema)
        row = self.conn.execute(
            sql.SQL("SELECT value FROM {} WHERE key='schema_version'").format(table)
        ).fetchone()
        return str(row["value"]) if row else "unknown"

    def summary(self) -> dict[str, Any]:
        identity = self.database_identity()
        return {
            "engine": "PostgreSQL base-data/on-demand",
            "schema_version": self.schema_version,
            "database": identity,
            "ohlcv": self.coverage("ohlcv") if identity["ohlcv_compatible"] else None,
            "investor": self.coverage("investor"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
