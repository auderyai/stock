from __future__ import annotations

import pandas as pd

from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings
from krx_research_nextgen.infrastructure.postgresql import open_connection


class AuxiliaryRepository:
    """Short-lived, read-only PostgreSQL queries for auxiliary screens."""

    def __init__(self, settings: PostgreSQLSettings | None = None) -> None:
        self._settings = settings or PostgreSQLSettings.from_c_stock_env()

    def _connect(self):
        return open_connection(
            self._settings,
            application_name="krx_nextgen_auxiliary",
        )

    def investor_rows(self, start, end) -> dict[str, list[dict]]:
        price_start = end - pd.Timedelta(days=60)
        with self._connect() as conn:
            master = [dict(row) for row in conn.execute("SELECT ticker,name,market FROM market.security_master").fetchall()]
            codes = [str(row["ticker"]).strip() for row in master]
            raw = [dict(row) for row in conn.execute(
                "SELECT stock_code,trade_date,side_code,source_fields FROM market_core.ls_investor_t1702_raw "
                "WHERE stock_code=ANY(%s) AND metric_code='0' AND exchange_code='K' AND trade_date BETWEEN %s AND %s",
                (codes, start, end),
            ).fetchall()]
            prices = [dict(row) for row in conn.execute(
                "SELECT ticker,trade_date,close,amount FROM market.ohlcv_daily "
                "WHERE ticker=ANY(%s) AND trade_date BETWEEN %s AND %s ORDER BY ticker,trade_date DESC",
                (codes, price_start.isoformat(), end.isoformat()),
            ).fetchall()]
        return {"raw": raw, "prices": prices, "master": master}

    def index_entries(self) -> list[dict]:
        query = """
            WITH ranked AS (
              SELECT o.*,row_number() OVER(PARTITION BY index_code ORDER BY trade_date DESC) rn
              FROM market_core.index_ohlcv_daily o
            )
            SELECT m.index_code,m.market,m.index_name,r.trade_date,r.close_price,
                   CASE WHEN p.close_price>0 THEN (r.close_price/p.close_price-1)*100 END daily_return
            FROM market_core.index_master m JOIN ranked r ON r.index_code=m.index_code AND r.rn=1
            LEFT JOIN ranked p ON p.index_code=m.index_code AND p.rn=2
            ORDER BY CASE m.index_code WHEN '1001' THEN 0 WHEN '2001' THEN 1 ELSE 2 END,m.market,m.index_name
        """
        with self._connect() as conn: return [dict(row) for row in conn.execute(query).fetchall()]

    def index_bars(self, code: str, limit: int = 100000) -> pd.DataFrame:
        query = """
            SELECT trade_date date,open_price open,high_price high,low_price low,
                   close_price close,volume
            FROM market_core.index_ohlcv_daily WHERE index_code=%s
            ORDER BY trade_date DESC LIMIT %s
        """
        with self._connect() as conn: rows = conn.execute(query, (code, limit)).fetchall()
        frame = pd.DataFrame(rows)
        if frame.empty: return pd.DataFrame(columns=("open","high","low","close","volume"))
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("open", "high", "low", "close", "volume"): frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.set_index("date").sort_index()
