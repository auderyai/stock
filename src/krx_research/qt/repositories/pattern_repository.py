from __future__ import annotations

from datetime import date

import pandas as pd

from krx_research.database import open_research_store
from krx_research.qt.models.pattern import Security


class PostgreSQLPatternRepository:
    """Read-only OHLCV gateway for deterministic local pattern analysis."""

    def __init__(self, database_target):
        self.database_target = database_target

    def _rows(self, statement: str, params=()) -> list[dict]:
        with open_research_store(self.database_target, read_only=True) as store:
            return [dict(row) for row in store.conn.execute(statement, params).fetchall()]

    def resolve(self, security: str) -> Security:
        value = str(security).strip()
        rows = self._rows(
            "SELECT btrim(ticker) code,name FROM market.security_master "
            "WHERE btrim(ticker)=%s OR name=%s "
            "ORDER BY CASE WHEN btrim(ticker)=%s THEN 0 ELSE 1 END LIMIT 2",
            (value.zfill(6) if value.isdigit() else value, value, value.zfill(6)),
        )
        if not rows:
            raise ValueError(f"종목을 찾을 수 없습니다: {value}")
        if len(rows) > 1 and not value.isdigit():
            raise ValueError(f"같은 종목명이 여러 개입니다. 종목코드를 입력하십시오: {value}")
        return Security(str(rows[0]["code"]), str(rows[0]["name"] or value))

    def search_securities(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        value, count = str(query).strip(), max(1, int(limit))
        if not value:
            return []
        pattern = f"%{value}%"
        rows = self._rows(
            "SELECT btrim(ticker) ticker,COALESCE(name,'') name,COALESCE(market,'') market "
            "FROM market.security_master WHERE btrim(ticker) ILIKE %s OR name ILIKE %s "
            "ORDER BY CASE WHEN btrim(ticker)=%s OR name=%s THEN 0 "
            "WHEN btrim(ticker) ILIKE %s OR name ILIKE %s THEN 1 ELSE 2 END,name,ticker LIMIT %s",
            (pattern, pattern, value.zfill(6) if value.isdigit() else value,
             value, f"{value}%", f"{value}%", count),
        )
        return [{key: str(row.get(key) or "") for key in ("ticker", "name", "market")}
                for row in rows]

    def history(self, start: date, end: date) -> pd.DataFrame:
        rows = self._rows(
            "SELECT btrim(o.ticker) stock_code,COALESCE(m.name,btrim(o.ticker)) stock_name,m.market,"
            "o.trade_date::date trade_date,o.close::double precision close,"
            "o.high::double precision high,o.low::double precision low,o.volume::double precision volume "
            "FROM market.ohlcv_daily o LEFT JOIN market.security_master m "
            "ON btrim(m.ticker)=btrim(o.ticker) "
            "WHERE o.trade_date BETWEEN %s AND %s AND o.close>0 "
            "ORDER BY btrim(o.ticker),o.trade_date",
            (start.isoformat(), end.isoformat()),
        )
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("지정 기간의 주가 자료가 없습니다.")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        return frame

    def latest(self, codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        rows = self._rows(
            "WITH ranked AS ("
            " SELECT btrim(o.ticker) stock_code,o.trade_date::date trade_date,"
            " o.open::double precision open,o.high::double precision high,"
            " o.low::double precision low,o.close::double precision close,"
            " COALESCE(o.amount,o.close*o.volume)::double precision trading_value,"
            " row_number() OVER(PARTITION BY btrim(o.ticker) ORDER BY o.trade_date DESC) rn"
            " FROM market.ohlcv_daily o WHERE btrim(o.ticker)=ANY(%s)"
            ") SELECT cur.stock_code,m.name stock_name,m.market,cur.trade_date,cur.open,cur.high,cur.low,"
            "cur.close,cur.trading_value,m.market_cap::double precision market_cap,"
            "CASE WHEN prev.close>0 THEN (cur.close/prev.close-1)*100 END rise_pct "
            "FROM ranked cur LEFT JOIN ranked prev ON prev.stock_code=cur.stock_code AND prev.rn=2 "
            "LEFT JOIN market.security_master m ON btrim(m.ticker)=cur.stock_code WHERE cur.rn=1",
            (codes,),
        )
        return {str(row["stock_code"]): row for row in rows}

    def market_context(self, end: date, limit: int = 320) -> pd.DataFrame:
        rows = self._rows(
            "WITH ranked AS (SELECT index_code,trade_date::date trade_date,"
            "close_price::double precision close,"
            "row_number() OVER(PARTITION BY index_code ORDER BY trade_date DESC) rn "
            "FROM market_core.index_ohlcv_daily WHERE index_code=ANY(%s) AND trade_date<=%s) "
            "SELECT index_code,trade_date,close FROM ranked WHERE rn<=%s "
            "ORDER BY index_code,trade_date",
            (["1001", "2001"], end.isoformat(), int(limit)),
        )
        frame = pd.DataFrame(rows)
        if frame.empty or set(frame.get("index_code", ())) != {"1001", "2001"}:
            raise ValueError("KOSPI·KOSDAQ 종합지수 DB 자료가 모두 필요합니다.")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        return frame

    def latest_date(self) -> date:
        rows = self._rows("SELECT max(trade_date)::date latest_date FROM market.ohlcv_daily")
        if not rows or not rows[0].get("latest_date"):
            raise ValueError("최신 주가 기준일을 찾을 수 없습니다.")
        return rows[0]["latest_date"]
