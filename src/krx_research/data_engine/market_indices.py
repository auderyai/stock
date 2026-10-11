"""Raw KRX index candles, separate from security OHLCV and calculated indicators."""
from __future__ import annotations

import datetime as dt
from psycopg import sql
import pandas as pd

DDL = """
CREATE SCHEMA IF NOT EXISTS market_core;
CREATE TABLE IF NOT EXISTS market_core.index_master (
 index_code varchar(12) PRIMARY KEY, market varchar(12) NOT NULL,
 index_name text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market_core.index_ohlcv_daily (
 index_code varchar(12) NOT NULL REFERENCES market_core.index_master(index_code),
 trade_date date NOT NULL, open_price numeric(20,4) NOT NULL,
 high_price numeric(20,4) NOT NULL, low_price numeric(20,4) NOT NULL,
 close_price numeric(20,4) NOT NULL, volume bigint,
 source text NOT NULL DEFAULT 'pykrx', retrieved_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(index_code, trade_date)
);
CREATE INDEX IF NOT EXISTS index_ohlcv_daily_date_idx ON market_core.index_ohlcv_daily(trade_date DESC);
ALTER TABLE market_core.index_ohlcv_daily ADD COLUMN IF NOT EXISTS trading_value numeric(26,2);
ALTER TABLE market_core.index_ohlcv_daily DROP COLUMN IF EXISTS daily_return_pct;
ALTER TABLE market_core.index_ohlcv_daily DROP COLUMN IF EXISTS weekly_return_pct;
ALTER TABLE market_core.index_ohlcv_daily DROP COLUMN IF EXISTS previous_trading_value;
"""


def ensure_schema(conn) -> None:
    conn.execute(DDL)


def list_indices(conn) -> list[dict]:
    return conn.execute("""SELECT m.index_code,m.index_name,m.market,
      MIN(d.trade_date) first_date,MAX(d.trade_date) last_date,COUNT(d.trade_date) bars
      FROM market_core.index_master m LEFT JOIN market_core.index_ohlcv_daily d
      USING(index_code) GROUP BY m.index_code ORDER BY m.market,m.index_name""").fetchall()


def index_list_snapshots(conn) -> list[dict]:
    """Read six stored daily bars per index without calculating or storing rates."""
    has_value = bool(conn.execute("""
      SELECT column_name FROM information_schema.columns
      WHERE table_schema='market_core' AND table_name='index_ohlcv_daily'
        AND column_name='trading_value'""").fetchone())
    amount = 'trading_value' if has_value else 'NULL::numeric AS trading_value'
    return conn.execute(f"""SELECT m.index_code,d.trade_date,d.close_price,
      d.trading_value
      FROM market_core.index_master m
      CROSS JOIN LATERAL (
        SELECT trade_date,close_price,{amount}
        FROM market_core.index_ohlcv_daily
        WHERE index_code=m.index_code ORDER BY trade_date DESC LIMIT 6
      ) d ORDER BY m.index_code,d.trade_date DESC""").fetchall()


def fetch_index(conn, code: str, start: dt.date | None = None,
                end: dt.date | None = None) -> pd.DataFrame:
    conditions = [sql.SQL("d.index_code=%s")]
    params: list = [code]
    if start:
        conditions.append(sql.SQL("d.trade_date >= %s"))
        params.append(start)
    if end:
        conditions.append(sql.SQL("d.trade_date <= %s"))
        params.append(end)
    rows = conn.execute(sql.SQL("""SELECT d.trade_date AS date,d.open_price AS open,
      d.high_price AS high,d.low_price AS low,d.close_price AS close,d.volume
      FROM market_core.index_ohlcv_daily d WHERE {} ORDER BY trade_date""").format(
        sql.SQL(" AND ").join(conditions)), params).fetchall()
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
