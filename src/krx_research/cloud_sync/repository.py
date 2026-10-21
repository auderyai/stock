from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import psycopg
from psycopg.rows import dict_row

from krx_research.data_engine.config import database_conninfo

from .archive import CloudArchiveError


@contextmanager
def open_cloud_connection(conninfo: str | None = None, *, read_only: bool = True):
    """Own cloud-sync PostgreSQL connections at the data-access boundary."""
    with psycopg.connect(
        conninfo or database_conninfo(), row_factory=dict_row, autocommit=True
    ) as connection:
        if read_only:
            connection.execute("SET default_transaction_read_only TO on")
        connection.autocommit = False
        yield connection


def menu5_complete(connection, target_date: date) -> bool:
    row = connection.execute(
        """WITH target AS (
               SELECT stock_code FROM market_core.cloud_stock_universe)
           SELECT count(*) AS targets, count(done.stock_code) AS completed
           FROM target LEFT JOIN market_core.ls_investor_t1702_checkpoint done
             ON done.stock_code=target.stock_code
            AND done.trade_date=%s AND done.exchange_code='K'""",
        (target_date,),
    ).fetchone()
    return bool(row and row["targets"] and row["targets"] == row["completed"])


def latest_cloud_date(connection) -> date:
    row = connection.execute(
        """SELECT max(trade_date) AS latest
           FROM market_core.ls_investor_t1702_checkpoint c
           WHERE EXISTS (
               SELECT 1 FROM market_core.venue_ohlcv_daily v
               WHERE v.trade_date=c.trade_date AND v.venue='COMBINED')"""
    ).fetchone()
    if not row or row["latest"] is None:
        raise CloudArchiveError("메뉴 5·7 완료 기준일을 찾지 못했습니다.")
    return row["latest"]
