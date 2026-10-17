from __future__ import annotations

import datetime as dt
from pathlib import Path

from psycopg import sql

from krx_research.application.xing_db.e2e_models import Menu2Snapshot, WriteCandidate
from krx_research.infrastructure.xing_db.postgresql_repository import PostgreSQLXingMenuRepository


class PostgreSQLE2EProbeRepository:
    """Read-oriented verification adapter over the production PostgreSQL repository."""

    def __init__(self) -> None:
        self._menu_repo = PostgreSQLXingMenuRepository(application_name="v41_e2e_probe")
        self._menu_repo.initialize()

    @property
    def conn(self):
        return self._menu_repo.conn

    def close(self) -> None:
        self._menu_repo.close()

    def latest_market_date(self) -> dt.date | None:
        return self._menu_repo.latest_market_date()

    def find_combined_gap(self, start: dt.date, end: dt.date) -> WriteCandidate | None:
        return self._find_gap(start, end, kind="combined")

    def find_investor_gap(self, start: dt.date, end: dt.date) -> WriteCandidate | None:
        return self._find_gap(start, end, kind="investor")

    def _find_gap(self, start: dt.date, end: dt.date, *, kind: str) -> WriteCandidate | None:
        base = self._menu_repo._repo
        cols = base._require_ohlcv()
        stock = sql.Identifier(cols["stock_code"])
        day = sql.Identifier(cols["trade_date"])
        table = base._ohlcv_table

        if kind == "combined":
            missing = sql.SQL(
                "NOT EXISTS (SELECT 1 FROM {}.venue_ohlcv_daily v "
                "WHERE v.stock_code::text=b.{}::text AND v.venue='COMBINED' "
                "AND v.trade_date::date=b.{}::date)"
            ).format(base._core_schema, stock, day)
            reason = "KRX 거래일 대비 COMBINED 일봉 결측"
        else:
            missing = sql.SQL(
                "NOT EXISTS (SELECT 1 FROM market_core.ls_investor_t1702_checkpoint c "
                "WHERE c.stock_code::text=b.{}::text AND c.exchange_code='K' "
                "AND c.trade_date=b.{}::date)"
            ).format(stock, day)
            reason = "KRX 거래일 대비 t1702 checkpoint 결측"

        # Prefer liquid index members, then newest missing date. SPACs are excluded by LS security master.
        query = sql.SQL(
            "WITH idx AS ("
            "  SELECT DISTINCT stock_code FROM market_core.ls_index_membership_raw "
            "  WHERE as_of_date=(SELECT MAX(as_of_date) FROM market_core.ls_index_membership_raw)"
            "), candidates AS ("
            "  SELECT DISTINCT b.{}::text AS stock_code, b.{}::date AS trade_date, "
            "         CASE WHEN idx.stock_code IS NULL THEN 1 ELSE 0 END AS priority "
            "  FROM {} b "
            "  JOIN market_core.ls_security_master sm ON sm.stock_code=b.{}::text "
            "  LEFT JOIN idx ON idx.stock_code=b.{}::text "
            "  WHERE b.{}::date BETWEEN %s AND %s AND {}"
            ") "
            "SELECT stock_code, trade_date FROM candidates "
            "ORDER BY priority, trade_date DESC, stock_code LIMIT 1"
        ).format(stock, day, table, stock, stock, day, missing)
        row = self.conn.execute(query, (start, end)).fetchone()
        if not row:
            return None
        return WriteCandidate(str(row["stock_code"]).zfill(6), row["trade_date"], reason)

    def find_existing_combined(self, start: dt.date, end: dt.date) -> WriteCandidate | None:
        row = self.conn.execute(
            """SELECT v.stock_code, v.trade_date::date AS trade_date
               FROM market_core.venue_ohlcv_daily v
               JOIN market_core.ls_security_master sm ON sm.stock_code=v.stock_code
               WHERE v.venue='COMBINED' AND v.trade_date::date BETWEEN %s AND %s
               ORDER BY CASE WHEN v.stock_code='005930' THEN 0 ELSE 1 END,
                        v.trade_date DESC, v.stock_code
               LIMIT 1""",
            (start, end),
        ).fetchone()
        if not row:
            return None
        return WriteCandidate(str(row["stock_code"]).zfill(6), row["trade_date"], "기존 COMBINED 행 force-refresh UPSERT 검증")

    def combined_row_count(self, stock_code: str, trade_date: dt.date) -> int:
        base = self._menu_repo._repo
        table = sql.SQL("{}.venue_ohlcv_daily").format(base._core_schema)
        row = self.conn.execute(
            sql.SQL(
                "SELECT COUNT(*)::int AS n FROM {} WHERE stock_code=%s AND venue='COMBINED' "
                "AND trade_date::date=%s"
            ).format(table),
            (stock_code, trade_date),
        ).fetchone()
        return int(row["n"])

    def find_completed_investor(self, start: dt.date, end: dt.date) -> WriteCandidate | None:
        row = self.conn.execute(
            """SELECT c.stock_code, c.trade_date
               FROM market_core.ls_investor_t1702_checkpoint c
               JOIN market_core.ls_security_master sm ON sm.stock_code=c.stock_code
               WHERE c.exchange_code='K' AND c.trade_date BETWEEN %s AND %s
                 AND (SELECT COUNT(*) FROM market_core.ls_investor_t1702_raw r
                      WHERE r.stock_code=c.stock_code AND r.trade_date=c.trade_date
                        AND r.exchange_code='K')=4
               ORDER BY CASE WHEN c.stock_code='005930' THEN 0 ELSE 1 END,
                        c.trade_date DESC, c.stock_code
               LIMIT 1""",
            (start, end),
        ).fetchone()
        if not row:
            return None
        return WriteCandidate(str(row["stock_code"]).zfill(6), row["trade_date"], "기존 t1702 4-matrix force-refresh UPSERT 검증")

    def investor_matrix_count(self, stock_code: str, trade_date: dt.date) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*)::int AS n
               FROM market_core.ls_investor_t1702_raw
               WHERE stock_code=%s AND trade_date=%s AND exchange_code='K'""",
            (stock_code, trade_date),
        ).fetchone()
        return int(row["n"])

    def investor_checkpoint_count(self, stock_code: str, trade_date: dt.date) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*)::int AS n
               FROM market_core.ls_investor_t1702_checkpoint
               WHERE stock_code=%s AND trade_date=%s AND exchange_code='K'""",
            (stock_code, trade_date),
        ).fetchone()
        return int(row["n"])

    def menu2_snapshot(self, as_of: dt.date) -> Menu2Snapshot:
        def scalar(query: str, params: tuple = ()) -> int:
            row = self.conn.execute(query, params).fetchone()
            return int(next(iter(row.values()))) if row else 0

        sector_master = scalar("SELECT COUNT(*)::int AS n FROM market_core.ls_sector_master")
        security_master = scalar("SELECT COUNT(*)::int AS n FROM market_core.ls_security_master")
        kospi200 = scalar(
            """SELECT COUNT(*)::int AS n FROM market_core.ls_index_membership_raw
               WHERE as_of_date=%s AND sector_name='KOSPI200'""", (as_of,)
        )
        kosdaq150 = scalar(
            """SELECT COUNT(*)::int AS n FROM market_core.ls_index_membership_raw
               WHERE as_of_date=%s AND sector_name='KOSDAQ150'""", (as_of,)
        )
        sector_daily = scalar(
            "SELECT COUNT(*)::int AS n FROM market_core.ls_sector_ohlcv_daily WHERE trade_date=%s", (as_of,)
        )
        market_index_sources = scalar(
            """SELECT COUNT(*)::int AS n FROM market_core.ls_sector_ohlcv_daily
               WHERE trade_date=%s AND (sector_code LIKE '0%%' OR sector_code LIKE '3%%')""",
            (as_of,),
        )
        market_indices_published = scalar(
            """SELECT COUNT(*)::int AS n
                 FROM market_core.ls_sector_ohlcv_daily s
                 JOIN market_core.index_ohlcv_daily i
                   ON i.trade_date=s.trade_date
                  AND i.index_code=CASE s.sector_code
                        WHEN '001' THEN '1001' WHEN '301' THEN '2001'
                        ELSE 'L' || s.sector_code END
                  AND i.open_price=s.open_price/100 AND i.high_price=s.high_price/100
                  AND i.low_price=s.low_price/100 AND i.close_price=s.close_price/100
                WHERE s.trade_date=%s
                  AND (s.sector_code LIKE '0%%' OR s.sector_code LIKE '3%%')""",
            (as_of,),
        )
        dup_sector_master = scalar(
            """SELECT COALESCE(SUM(n-1),0)::int AS n FROM
               (SELECT COUNT(*) n FROM market_core.ls_sector_master GROUP BY sector_code HAVING COUNT(*)>1) x"""
        )
        dup_security_master = scalar(
            """SELECT COALESCE(SUM(n-1),0)::int AS n FROM
               (SELECT COUNT(*) n FROM market_core.ls_security_master GROUP BY stock_code HAVING COUNT(*)>1) x"""
        )
        dup_membership = scalar(
            """SELECT COALESCE(SUM(n-1),0)::int AS n FROM
               (SELECT COUNT(*) n FROM market_core.ls_index_membership_raw
                GROUP BY as_of_date,sector_code,stock_code HAVING COUNT(*)>1) x"""
        )
        dup_sector_daily = scalar(
            """SELECT COALESCE(SUM(n-1),0)::int AS n FROM
               (SELECT COUNT(*) n FROM market_core.ls_sector_ohlcv_daily
                GROUP BY sector_code,trade_date HAVING COUNT(*)>1) x"""
        )
        return Menu2Snapshot(
            as_of=as_of,
            sector_master=sector_master,
            security_master=security_master,
            kospi200=kospi200,
            kosdaq150=kosdaq150,
            sector_daily=sector_daily,
            market_index_sources=market_index_sources,
            market_indices_published=market_indices_published,
            duplicate_sector_master=dup_sector_master,
            duplicate_security_master=dup_security_master,
            duplicate_membership=dup_membership,
            duplicate_sector_daily=dup_sector_daily,
        )
