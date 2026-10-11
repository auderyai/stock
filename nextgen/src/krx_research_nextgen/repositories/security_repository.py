from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings
from krx_research_nextgen.models.security import SecurityRecord


class SecurityRepository:
    _CODE_ALIASES = ("stock_code", "ticker", "code")
    _NAME_ALIASES = ("stock_name", "name")
    _MARKET_ALIASES = ("market", "market_name", "market_type")

    def __init__(self, settings: PostgreSQLSettings | None = None) -> None:
        self._settings = settings or PostgreSQLSettings.from_c_stock_env()
        self._conn = psycopg.connect(
            **self._settings.connect_kwargs(),
            row_factory=dict_row,
            autocommit=True,
            application_name="krx_nextgen_finplot_stage3_security",
        )
        self._schema, self._table, self._columns = self._resolve_master()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.close()

    def _columns_for(self, schema: str, table: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
            (schema, table),
        ).fetchall()
        return {str(r["column_name"]) for r in rows}

    @staticmethod
    def _pick(columns: set[str], aliases: tuple[str, ...]) -> str | None:
        return next((x for x in aliases if x in columns), None)

    def _resolve_master(self) -> tuple[str, str, dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog','information_schema')
              AND table_type IN ('BASE TABLE','FOREIGN')
              AND table_name = ANY(%s::text[])
            ORDER BY CASE WHEN table_schema='market' THEN 0
                          WHEN table_schema='public' THEN 1 ELSE 2 END,
                     table_schema, table_name
            """,
            (["security_master", "securities"],),
        ).fetchall()
        pairs = [(str(r["table_schema"]), str(r["table_name"])) for r in rows]
        preferred = (
            self._settings.preferred_master_schema,
            self._settings.preferred_master_table,
        )
        ordered = ([preferred] if preferred in pairs else []) + [p for p in pairs if p != preferred]

        for schema, table in ordered:
            cols = self._columns_for(schema, table)
            code = self._pick(cols, self._CODE_ALIASES)
            name = self._pick(cols, self._NAME_ALIASES)
            market = self._pick(cols, self._MARKET_ALIASES)
            if code and name:
                mapping = {"stock_code": code, "stock_name": name}
                if market:
                    mapping["market"] = market
                return schema, table, mapping

        raise RuntimeError("No compatible security-master relation found.")

    @property
    def relation_name(self) -> str:
        return f"{self._schema}.{self._table}"

    def search(self, keyword: str = "", limit: int = 300) -> list[SecurityRecord]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")

        code_col = self._columns["stock_code"]
        name_col = self._columns["stock_name"]
        market_col = self._columns.get("market")
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self._schema),
            sql.Identifier(self._table),
        )
        market_expr = (
            sql.SQL("COALESCE({}::text,'')").format(sql.Identifier(market_col))
            if market_col else sql.SQL("''::text")
        )
        keyword = keyword.strip()

        if keyword:
            pattern = f"%{keyword}%"
            query = sql.SQL("""
                SELECT {code}::text AS stock_code,
                       {name}::text AS stock_name,
                       {market} AS market
                FROM {table}
                WHERE {code}::text ILIKE %s OR {name}::text ILIKE %s
                ORDER BY CASE WHEN {code}::text=%s THEN 0
                              WHEN {name}::text=%s THEN 1 ELSE 2 END,
                         {name}::text, {code}::text
                LIMIT %s
            """).format(
                code=sql.Identifier(code_col),
                name=sql.Identifier(name_col),
                market=market_expr,
                table=table,
            )
            rows = self._conn.execute(
                query,
                (pattern, pattern, keyword, keyword, int(limit)),
            ).fetchall()
        else:
            query = sql.SQL("""
                SELECT {code}::text AS stock_code,
                       {name}::text AS stock_name,
                       {market} AS market
                FROM {table}
                WHERE {code} IS NOT NULL AND {name} IS NOT NULL
                ORDER BY {name}::text, {code}::text
                LIMIT %s
            """).format(
                code=sql.Identifier(code_col),
                name=sql.Identifier(name_col),
                market=market_expr,
                table=table,
            )
            rows = self._conn.execute(query, (int(limit),)).fetchall()

        result: list[SecurityRecord] = []
        for row in rows:
            code = str(row["stock_code"]).strip()
            if code.isdigit():
                code = code.zfill(6)
            result.append(
                SecurityRecord(
                    stock_code=code,
                    stock_name=str(row["stock_name"] or "").strip(),
                    market=str(row["market"] or "").strip(),
                )
            )
        return result
