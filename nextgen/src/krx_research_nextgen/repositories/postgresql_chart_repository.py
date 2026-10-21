from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
from psycopg import sql

from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings
from krx_research_nextgen.infrastructure.postgresql import open_connection


OHLCV_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("stock_code", "ticker"),
    "trade_date": ("trade_date",),
    "open": ("open_price", "open"),
    "high": ("high_price", "high"),
    "low": ("low_price", "low"),
    "close": ("close_price", "close"),
    "volume": ("volume",),
    "trading_value": ("trading_value", "trade_value", "amount", "turnover"),
}

MASTER_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("stock_code", "ticker", "code"),
    "stock_name": ("stock_name", "name"),
}


@dataclass(frozen=True)
class RelationInfo:
    schema: str
    table: str
    columns: dict[str, str]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.table}"


class PostgreSQLChartRepository:
    """Read-only PostgreSQL repository for chart data.

    Responsibilities:
    - Discover compatible OHLCV/master relations.
    - Execute parameterized SQL.
    - Return normalized pandas data.
    - Never calculate indicators or render charts.
    """

    def __init__(self, settings: PostgreSQLSettings | None = None) -> None:
        self._settings = settings or PostgreSQLSettings.from_c_stock_env()
        self._conn = open_connection(
            self._settings,
            application_name="krx_nextgen_finplot_stage2",
        )
        self._ohlcv = self._resolve_ohlcv_relation()
        self._ohlcv_types = self._relation_columns(self._ohlcv.schema, self._ohlcv.table)
        self._master = self._resolve_master_relation()

    def __enter__(self) -> "PostgreSQLChartRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.close()

    @staticmethod
    def _canonical_map(columns: Iterable[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
        available = set(columns)
        result: dict[str, str] = {}
        for canonical, choices in aliases.items():
            selected = next((candidate for candidate in choices if candidate in available), None)
            if selected:
                result[canonical] = selected
        return result

    def _relation_columns(self, schema: str, table: str) -> dict[str, str]:
        rows = self._conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (schema, table),
        ).fetchall()
        return {str(r["column_name"]): str(r["data_type"]) for r in rows}

    def _find_relations(self, table_names: list[str]) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_type IN ('BASE TABLE', 'FOREIGN')
              AND table_name = ANY(%s::text[])
            ORDER BY table_schema, table_name
            """,
            (table_names,),
        ).fetchall()
        return [(str(r["table_schema"]), str(r["table_name"])) for r in rows]

    def _resolve_ohlcv_relation(self) -> RelationInfo:
        preferred = (
            self._settings.preferred_ohlcv_schema,
            self._settings.preferred_ohlcv_table,
        )
        candidates = list(dict.fromkeys([
            self._settings.preferred_ohlcv_table,
            "ohlcv_daily",
        ]))
        relations = self._find_relations(candidates)

        ordered: list[tuple[str, str]] = []
        if preferred in relations:
            ordered.append(preferred)
        for schema in ("market", "public"):
            for table in candidates:
                pair = (schema, table)
                if pair in relations and pair not in ordered:
                    ordered.append(pair)
        for pair in relations:
            if pair not in ordered:
                ordered.append(pair)

        required = {"stock_code", "trade_date", "open", "high", "low", "close", "volume"}
        for schema, table in ordered:
            cols = self._relation_columns(schema, table)
            mapped = self._canonical_map(cols, OHLCV_ALIASES)
            if required.issubset(mapped):
                return RelationInfo(schema, table, mapped)

        rendered = ", ".join(f"{s}.{t}" for s, t in relations) or "(none)"
        raise RuntimeError(f"No compatible OHLCV relation found. candidates={rendered}")

    def _resolve_master_relation(self) -> RelationInfo | None:
        candidates = list(dict.fromkeys([
            self._settings.preferred_master_table,
            "security_master",
            "securities",
        ]))
        relations = self._find_relations(candidates)
        preferred = (
            self._settings.preferred_master_schema,
            self._settings.preferred_master_table,
        )
        ordered = ([preferred] if preferred in relations else [])
        ordered += [p for p in relations if p not in ordered]

        required = {"stock_code", "stock_name"}
        for schema, table in ordered:
            cols = self._relation_columns(schema, table)
            mapped = self._canonical_map(cols, MASTER_ALIASES)
            if required.issubset(mapped):
                return RelationInfo(schema, table, mapped)
        return None

    @property
    def ohlcv_relation(self) -> str:
        return self._ohlcv.qualified_name

    @property
    def master_relation(self) -> str | None:
        return None if self._master is None else self._master.qualified_name

    def diagnostics(self) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT current_database() AS database_name,
                   current_user AS current_user,
                   current_setting('server_version') AS server_version
            """
        ).fetchone()
        return {
            "database": row["database_name"],
            "user": row["current_user"],
            "server_version": row["server_version"],
            "ohlcv_relation": self.ohlcv_relation,
            "ohlcv_columns": dict(self._ohlcv.columns),
            "master_relation": self.master_relation,
        }

    def sample_latest_symbol(self) -> str:
        c = self._ohlcv.columns
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self._ohlcv.schema),
            sql.Identifier(self._ohlcv.table),
        )
        query = sql.SQL(
            "SELECT {ticker}::text AS stock_code "
            "FROM {table} "
            "WHERE {ticker} IS NOT NULL AND {date} IS NOT NULL "
            "ORDER BY {date} DESC LIMIT 1"
        ).format(
            ticker=sql.Identifier(c["stock_code"]),
            date=sql.Identifier(c["trade_date"]),
            table=table,
        )
        row = self._conn.execute(query).fetchone()
        if not row or not row["stock_code"]:
            raise RuntimeError("OHLCV table contains no ticker.")
        return str(row["stock_code"]).strip().zfill(6)

    def stock_name(self, symbol: str) -> str | None:
        if self._master is None:
            return None
        c = self._master.columns
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self._master.schema),
            sql.Identifier(self._master.table),
        )
        query = sql.SQL(
            "SELECT {name}::text AS stock_name "
            "FROM {table} WHERE {ticker}::text=%s LIMIT 1"
        ).format(
            name=sql.Identifier(c["stock_name"]),
            ticker=sql.Identifier(c["stock_code"]),
            table=table,
        )
        row = self._conn.execute(query, (str(symbol).zfill(6),)).fetchone()
        if not row:
            return None
        value = row["stock_name"]
        return None if value is None else str(value).strip()

    def load_recent_ohlcv(self, symbol: str, limit: int = 550) -> pd.DataFrame:
        if limit < 80 or limit > 10000:
            raise ValueError("limit must be between 80 and 10000")

        c = self._ohlcv.columns
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self._ohlcv.schema),
            sql.Identifier(self._ohlcv.table),
        )

        query = sql.SQL(
            """
            SELECT *
            FROM (
                SELECT
                    {date}::date AS trade_date,
                    {open}::double precision AS open,
                    {high}::double precision AS high,
                    {low}::double precision AS low,
                    {close}::double precision AS close,
                    COALESCE({volume}, 0)::double precision AS volume
                FROM {table}
                WHERE {ticker}::text=%s
                ORDER BY {date} DESC
                LIMIT %s
            ) recent
            ORDER BY trade_date ASC
            """
        ).format(
            date=sql.Identifier(c["trade_date"]),
            open=sql.Identifier(c["open"]),
            high=sql.Identifier(c["high"]),
            low=sql.Identifier(c["low"]),
            close=sql.Identifier(c["close"]),
            volume=sql.Identifier(c["volume"]),
            ticker=sql.Identifier(c["stock_code"]),
            table=table,
        )
        rows = self._conn.execute(query, (str(symbol).zfill(6), int(limit))).fetchall()
        if not rows:
            raise RuntimeError(f"No OHLCV rows found for symbol {symbol}")

        frame = pd.DataFrame(rows)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
        frame = frame.set_index("trade_date").sort_index()
        for col in ("open", "high", "low", "close", "volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        if frame.empty:
            raise RuntimeError(f"OHLCV rows for {symbol} became empty after normalization.")
        return frame

    def load_investor_flow(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Return daily net values grouped into the three legacy chart categories."""
        rows = []
        if self._conn.execute("SELECT to_regclass('market_core.investor_flow_daily') AS t").fetchone()["t"]:
            rows = self._conn.execute(
                """
                SELECT trade_date,
                       CASE
                         WHEN investor_type IN ('FINANCIAL_INVESTMENT','INSURANCE','INVESTMENT_TRUST','PRIVATE_FUND','BANK','OTHER_FINANCE','PENSION') THEN 'institution'
                         WHEN investor_type IN ('FOREIGN','OTHER_FOREIGN') THEN 'foreign'
                         WHEN investor_type='INDIVIDUAL' THEN 'individual'
                       END AS category,
                       sum(buy_value-sell_value)::double precision AS net_value
                FROM market_core.investor_flow_daily
                WHERE stock_code=%s AND trade_date BETWEEN %s AND %s
                  AND investor_type IN ('FINANCIAL_INVESTMENT','INSURANCE','INVESTMENT_TRUST','PRIVATE_FUND','BANK','OTHER_FINANCE','PENSION','FOREIGN','OTHER_FOREIGN','INDIVIDUAL')
                GROUP BY trade_date, category
                ORDER BY trade_date
                """,
                (str(symbol).zfill(6), pd.Timestamp(start).date(), pd.Timestamp(end).date()),
            ).fetchall()
        if rows:
            frame = pd.DataFrame(rows); frame["trade_date"] = pd.to_datetime(frame["trade_date"])
            return frame.pivot_table(index="trade_date", columns="category", values="net_value", aggfunc="sum").reindex(columns=["institution", "foreign", "individual"])
        return self._load_ls_investor_flow(symbol, start, end)

    def _load_ls_investor_flow(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        if "trading_value" not in self._ohlcv.columns or not self._conn.execute(
            "SELECT to_regclass('market_core.ls_investor_t1702_raw') AS t"
        ).fetchone()["t"]:
            return pd.DataFrame(columns=["institution", "foreign", "individual"])
        def total(source: str, fields: tuple[str, ...]):
            return sql.SQL(" + ").join(
                sql.SQL("abs(COALESCE(NULLIF({}->>{},''),'0')::numeric)").format(
                    sql.SQL(source), sql.Literal(field),
                ) for field in fields
            )
        institution = ("tjj0000", "tjj0001", "tjj0002", "tjj0003", "tjj0004", "tjj0005")
        foreign, individual = ("tjj0009", "tjj0010"), ("tjj0008",)
        table = sql.SQL("{}.{}").format(sql.Identifier(self._ohlcv.schema), sql.Identifier(self._ohlcv.table))
        columns = self._ohlcv.columns
        date = sql.Identifier("o", columns["trade_date"])
        textual_date = self._ohlcv_types.get(columns["trade_date"]) in {"character", "character varying", "text"}
        date_match = sql.SQL("{}=p.trade_date::text").format(date) if textual_date else sql.SQL("{}=p.trade_date").format(date)
        first, last = pd.Timestamp(start).date(), pd.Timestamp(end).date()
        price_dates = (first.isoformat(), last.isoformat()) if textual_date else (first, last)
        query = sql.SQL("""
            WITH raw AS (
              SELECT trade_date,side_code,source_fields,
                     abs(COALESCE(NULLIF(source_fields->>'value',''),'0')::numeric) reported
              FROM market_core.ls_investor_t1702_raw
              WHERE stock_code=%s AND exchange_code='K' AND metric_code='0'
                AND trade_date BETWEEN %s AND %s
            ), paired AS (
              SELECT b.trade_date,b.source_fields buy,s.source_fields sell,b.reported
              FROM raw b JOIN raw s USING(trade_date)
              WHERE b.side_code='1' AND s.side_code='2' AND b.reported>0
                AND abs(b.reported-s.reported)<=greatest(1,b.reported*.005)
            )
            SELECT p.trade_date,
                   (({inst_b})-({inst_s}))*unit.factor::double precision institution,
                   (({fb})-({fs}))*unit.factor::double precision foreign,
                   (({pb})-({ps}))*unit.factor::double precision individual
            FROM paired p JOIN {table} o
              ON {ticker}::text=%s AND {date} BETWEEN %s AND %s AND {date_match}
            CROSS JOIN LATERAL (
              SELECT factor FROM (VALUES (1::numeric),(1000::numeric),(1000000::numeric)) f(factor)
              WHERE {amount}::numeric>0
                AND abs(p.reported*factor-{amount}::numeric)/{amount}::numeric<=.02
              LIMIT 1
            ) unit ORDER BY p.trade_date
        """).format(
            inst_b=total("p.buy", institution), inst_s=total("p.sell", institution),
            fb=total("p.buy", foreign), fs=total("p.sell", foreign),
            pb=total("p.buy", individual), ps=total("p.sell", individual),
            table=table, ticker=sql.Identifier("o", columns["stock_code"]), date=date, date_match=date_match,
            amount=sql.Identifier("o", columns["trading_value"]),
        )
        code = str(symbol).zfill(6)
        rows = self._conn.execute(query, (code, first, last, code, *price_dates)).fetchall()
        if not rows: return pd.DataFrame(columns=["institution", "foreign", "individual"])
        return pd.DataFrame(rows).assign(trade_date=lambda x: pd.to_datetime(x.trade_date)).set_index("trade_date")
