from __future__ import annotations

from datetime import date

from psycopg import sql


class CoreSchemaMigrator:
    """Create only PostgreSQL facts/runtime tables owned by the v30+ data engine."""

    def __init__(self, schema: str = "market_core") -> None:
        self.schema = schema
        self._schema = sql.Identifier(schema)

    def apply(self, conn) -> None:
        s = self._schema
        statements = (
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(s),
            sql.SQL("CREATE SCHEMA IF NOT EXISTS legacy_archive"),
            sql.SQL("CREATE TABLE IF NOT EXISTS {}.schema_meta (key text PRIMARY KEY, value text NOT NULL)").format(s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {}.venue_ohlcv_daily (
                venue varchar(16) NOT NULL, stock_code varchar(6) NOT NULL, trade_date date NOT NULL,
                open_price double precision NOT NULL, high_price double precision NOT NULL,
                low_price double precision NOT NULL, close_price double precision NOT NULL,
                volume bigint NOT NULL DEFAULT 0, amount bigint, source text NOT NULL DEFAULT 'LS',
                source_document text NOT NULL DEFAULT '', retrieved_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (venue, stock_code, trade_date)
            )""").format(s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {}.investor_flow_daily (
                stock_code varchar(6) NOT NULL, trade_date date NOT NULL, investor_type text NOT NULL,
                buy_volume bigint NOT NULL DEFAULT 0, sell_volume bigint NOT NULL DEFAULT 0,
                buy_value bigint NOT NULL DEFAULT 0, sell_value bigint NOT NULL DEFAULT 0,
                source text NOT NULL DEFAULT 'pykrx', retrieved_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (stock_code, trade_date, investor_type)
            ) PARTITION BY RANGE (trade_date)""").format(s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {}.update_state (
                dataset text NOT NULL, market text NOT NULL, last_complete_date date NOT NULL,
                details jsonb NOT NULL DEFAULT '{{}}'::jsonb, updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (dataset, market)
            )""").format(s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {}.collection_coverage (
                dataset text NOT NULL, market text NOT NULL, trade_date date NOT NULL,
                status text NOT NULL, row_count bigint NOT NULL DEFAULT 0,
                details jsonb NOT NULL DEFAULT '{{}}'::jsonb, checked_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (dataset, market, trade_date)
            )""").format(s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {}.update_runs (
                run_id bigserial PRIMARY KEY, target_date date NOT NULL, mode text NOT NULL,
                status text NOT NULL, ohlcv_rows bigint NOT NULL DEFAULT 0,
                investor_rows bigint NOT NULL DEFAULT 0, message text,
                started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
            )""").format(s),
            sql.SQL("""CREATE TABLE IF NOT EXISTS {}.corporate_actions (
                stock_code varchar(6) NOT NULL, action_date date NOT NULL,
                action_type text NOT NULL, ratio double precision, source text,
                retrieved_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (stock_code, action_date, action_type)
            )""").format(s),
        )
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            sql.SQL("INSERT INTO {}.schema_meta(key,value) VALUES('schema_version','31') "
                    "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value").format(s)
        )

    def ensure_investor_partition(self, conn, year: int) -> None:
        name = sql.Identifier(f"investor_flow_daily_{int(year)}")
        start, end = date(int(year), 1, 1), date(int(year) + 1, 1, 1)
        conn.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} PARTITION OF {}.investor_flow_daily "
                    "FOR VALUES FROM (%s) TO (%s)").format(self._schema, name, self._schema),
            [start, end],
        )
