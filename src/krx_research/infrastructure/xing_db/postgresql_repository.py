from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import pandas as pd
from psycopg import sql

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository


class PostgreSQLXingMenuRepository:
    """PostgreSQL adapter for V40 menu 2/5/7 LS data.

    Existing BaseDataRepository remains the owner of canonical OHLCV/venue tables.
    LS-specific master/raw tables live in market_core and use idempotent UPSERTs.
    """

    DDL = """
    CREATE SCHEMA IF NOT EXISTS market_core;

    CREATE TABLE IF NOT EXISTS market_core.ls_sector_master (
      sector_code varchar(3) PRIMARY KEY,
      sector_name text NOT NULL,
      source_fields jsonb NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS market_core.ls_security_master (
      stock_code varchar(6) PRIMARY KEY,
      stock_name text NOT NULL,
      source_fields jsonb NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS market_core.ls_index_membership_raw (
      as_of_date date NOT NULL,
      sector_code varchar(3) NOT NULL,
      sector_name text NOT NULL,
      stock_code varchar(6) NOT NULL,
      source_fields jsonb NOT NULL,
      collected_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(as_of_date, sector_code, stock_code)
    );

    CREATE TABLE IF NOT EXISTS market_core.ls_sector_ohlcv_daily (
      sector_code varchar(3) NOT NULL,
      trade_date date NOT NULL,
      open_price numeric,
      high_price numeric,
      low_price numeric,
      close_price numeric,
      volume numeric,
      amount numeric,
      source_fields jsonb NOT NULL,
      collected_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(sector_code, trade_date)
    );

    CREATE TABLE IF NOT EXISTS market_core.ls_investor_t1702_raw (
      stock_code varchar(6) NOT NULL,
      trade_date date NOT NULL,
      metric_code char(1) NOT NULL CHECK (metric_code IN ('0','1')),
      side_code char(1) NOT NULL CHECK (side_code IN ('1','2')),
      exchange_code char(1) NOT NULL DEFAULT 'K',
      source_fields jsonb NOT NULL,
      collected_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(stock_code,trade_date,metric_code,side_code,exchange_code)
    );

    CREATE TABLE IF NOT EXISTS market_core.ls_investor_t1702_checkpoint (
      stock_code varchar(6) NOT NULL,
      trade_date date NOT NULL,
      exchange_code char(1) NOT NULL,
      completed_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(stock_code,trade_date,exchange_code)
    );
    """

    SPAC = re.compile(r"(?:스\s*팩|기업인수목적|SPAC)", re.I)

    def __init__(self, settings: DataEngineSettings | None = None,
                 *, application_name: str = "xing_db_menu_v40") -> None:
        self._repo = BaseDataRepository(
            settings or DataEngineSettings.from_environment(), application_name=application_name
        )

    @property
    def conn(self):
        return self._repo.conn

    def initialize(self) -> None:
        self._repo.initialize_schema()
        with self.conn.transaction():
            self.conn.execute(self.DDL)

    def close(self) -> None:
        close = getattr(self._repo, "close", None)
        if callable(close):
            close()
            return
        exit_method = getattr(self._repo, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)

    def latest_market_date(self) -> dt.date | None:
        return self._repo.latest_ohlcv_date()

    def upsert_sector_master(self, rows: list[dict[str, Any]]) -> int:
        values = []
        for row in rows:
            code = str(row.get("upcode") or "").strip()
            name = str(row.get("hname") or "").strip()
            if re.fullmatch(r"\d{3}", code) and name:
                values.append((code, name, self._json_dumps(row)))
        if not values:
            return 0
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO market_core.ls_sector_master
                   (sector_code,sector_name,source_fields) VALUES (%s,%s,%s::jsonb)
                   ON CONFLICT(sector_code) DO UPDATE SET
                     sector_name=EXCLUDED.sector_name,
                     source_fields=EXCLUDED.source_fields, updated_at=now()""",
                values,
            )
        return len(values)

    def upsert_security_master(self, rows: list[dict[str, Any]]) -> int:
        values = []
        for row in rows:
            code = str(row.get("shcode") or "").strip()
            name = str(row.get("hname") or "").strip()
            if re.fullmatch(r"\d{6}", code) and name and not self.SPAC.search(name):
                values.append((code, name, self._json_dumps(row)))
        if not values:
            return 0
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO market_core.ls_security_master
                   (stock_code,stock_name,source_fields) VALUES (%s,%s,%s::jsonb)
                   ON CONFLICT(stock_code) DO UPDATE SET
                     stock_name=EXCLUDED.stock_name,
                     source_fields=EXCLUDED.source_fields, updated_at=now()""",
                values,
            )
        return len(values)

    def replace_index_membership(self, as_of: dt.date, sector_code: str, sector_name: str,
                                 rows: list[dict[str, Any]]) -> int:
        values = []
        for row in rows:
            code = str(row.get("shcode") or "").strip()
            name = str(row.get("hname") or "").strip()
            if re.fullmatch(r"[0-9A-Z]{6}", code) and not self.SPAC.search(name):
                values.append((as_of, sector_code, sector_name, code,
                               self._json_dumps(row)))
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM market_core.ls_index_membership_raw WHERE as_of_date=%s AND sector_code=%s",
                (as_of, sector_code),
            )
            if values:
                cur.executemany(
                    """INSERT INTO market_core.ls_index_membership_raw
                       (as_of_date,sector_code,sector_name,stock_code,source_fields)
                       VALUES (%s,%s,%s,%s,%s::jsonb)""",
                    values,
                )
        return len(values)

    def upsert_sector_daily(self, sector_code: str, rows: list[dict[str, Any]]) -> int:
        values = []
        for row in rows:
            stamp = str(row.get("date") or "").strip()
            try:
                day = dt.datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue
            values.append((
                sector_code, day,
                self._num(row.get("open")), self._num(row.get("high")),
                self._num(row.get("low")), self._num(row.get("close")),
                self._num(row.get("jdiff_vol") or row.get("volume")),
                self._num(row.get("value")), self._json_dumps(row),
            ))
        if not values:
            return 0
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO market_core.ls_sector_ohlcv_daily
                   (sector_code,trade_date,open_price,high_price,low_price,close_price,volume,amount,source_fields)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT(sector_code,trade_date) DO UPDATE SET
                     open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
                     low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
                     volume=EXCLUDED.volume, amount=EXCLUDED.amount,
                     source_fields=EXCLUDED.source_fields, collected_at=now()""",
                values,
            )
        return len(values)

    def completed_sector_codes(self, as_of: dt.date) -> set[str]:
        rows = self.conn.execute(
            "SELECT sector_code FROM market_core.ls_sector_ohlcv_daily WHERE trade_date=%s",
            (as_of,),
        ).fetchall()
        return {str(row["sector_code"]).strip() for row in rows if row.get("sector_code")}

    def list_stock_codes(self, ticker: str | None = None, limit: int = 0,
                         offset: int = 0) -> list[str]:
        if ticker:
            token = str(ticker).strip()
            code = token.zfill(6) if token.isdigit() else ""
            if re.fullmatch(r"\d{6}", code):
                return [code]
            rows = self.conn.execute(
                "SELECT stock_code FROM market_core.ls_security_master WHERE stock_name=%s ORDER BY stock_code",
                (token,),
            ).fetchall()
            matches = [str(r["stock_code"]).zfill(6) for r in rows if str(r.get("stock_code") or "").isdigit()]
            if not matches:
                raise ValueError(f"종목을 찾을 수 없습니다: {token!r} (6자리 코드 또는 정확한 종목명 입력)")
            if len(matches) > 1:
                raise ValueError(f"동일 종목명이 여러 개입니다: {token!r} -> {', '.join(matches)}; 6자리 코드를 입력하십시오.")
            return matches
        cols = self._repo._require_ohlcv()
        stock = sql.Identifier(cols["stock_code"])
        table = self._repo._ohlcv_table
        query = sql.SQL("SELECT DISTINCT {} AS stock_code FROM {} ORDER BY {}").format(stock, table, stock)
        rows = self.conn.execute(query).fetchall()
        codes = [str(r["stock_code"]).zfill(6) for r in rows if str(r["stock_code"]).isdigit()]
        if offset < 0:
            raise ValueError("offset은 0 이상이어야 합니다.")
        selected = codes[offset:]
        return selected[:limit] if limit else selected

    def list_stock_trade_dates(self, stock_code: str, start: dt.date, end: dt.date) -> list[dt.date]:
        cols = self._repo._require_ohlcv()
        stock = sql.Identifier(cols["stock_code"])
        date = sql.Identifier(cols["trade_date"])
        table = self._repo._ohlcv_table
        query = sql.SQL(
            "SELECT DISTINCT {}::date AS trade_date FROM {} WHERE {}=%s "
            "AND {}::date BETWEEN %s AND %s ORDER BY trade_date"
        ).format(date, table, stock, date)
        return [r["trade_date"] for r in self.conn.execute(query, (stock_code, start, end)).fetchall()]

    def stock_trade_dates_by_code(self, stock_codes: list[str], start: dt.date,
                                  end: dt.date) -> dict[str, set[dt.date]]:
        if not stock_codes: return {}
        cols = self._repo._require_ohlcv(); stock = sql.Identifier(cols["stock_code"])
        date = sql.Identifier(cols["trade_date"]); table = self._repo._ohlcv_table
        query = sql.SQL(
            "SELECT {}::text AS stock_code, {}::date AS trade_date FROM {} "
            "WHERE {}=ANY(%s) AND {}::date BETWEEN %s AND %s GROUP BY 1,2"
        ).format(stock, date, table, stock, date)
        result: dict[str, set[dt.date]] = {}
        for row in self.conn.execute(query, (stock_codes, start, end)).fetchall():
            result.setdefault(str(row["stock_code"]).zfill(6), set()).add(row["trade_date"])
        return result

    def completed_investor_dates(self, stock_code: str, start: dt.date, end: dt.date,
                                 exchange_code: str = "K") -> set[dt.date]:
        rows = self.conn.execute(
            """SELECT trade_date FROM market_core.ls_investor_t1702_checkpoint
               WHERE stock_code=%s AND exchange_code=%s AND trade_date BETWEEN %s AND %s""",
            (stock_code, exchange_code, start, end),
        ).fetchall()
        return {r["trade_date"] for r in rows}

    def completed_investor_dates_by_code(self, stock_codes: list[str], start: dt.date,
                                         end: dt.date, exchange_code: str = "K") -> dict[str, set[dt.date]]:
        if not stock_codes: return {}
        rows = self.conn.execute(
            """SELECT stock_code,trade_date FROM market_core.ls_investor_t1702_checkpoint
               WHERE stock_code=ANY(%s) AND exchange_code=%s AND trade_date BETWEEN %s AND %s""",
            (stock_codes, exchange_code, start, end),
        ).fetchall()
        result: dict[str, set[dt.date]] = {}
        for row in rows: result.setdefault(str(row["stock_code"]).zfill(6), set()).add(row["trade_date"])
        return result

    def upsert_investor_raw(self, stock_code: str,
                            found: dict[tuple[dt.date, str, str], dict[str, Any]],
                            complete_days: list[dt.date], exchange_code: str = "K") -> int:
        raw_values = [
            (stock_code, day, metric, side, exchange_code, self._json_dumps(row))
            for (day, metric, side), row in found.items()
        ]
        with self.conn.transaction(), self.conn.cursor() as cur:
            if raw_values:
                cur.executemany(
                    """INSERT INTO market_core.ls_investor_t1702_raw
                       (stock_code,trade_date,metric_code,side_code,exchange_code,source_fields)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT(stock_code,trade_date,metric_code,side_code,exchange_code)
                       DO UPDATE SET source_fields=EXCLUDED.source_fields,collected_at=now()""",
                    raw_values,
                )
            if complete_days:
                cur.executemany(
                    """INSERT INTO market_core.ls_investor_t1702_checkpoint
                       (stock_code,trade_date,exchange_code) VALUES (%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    [(stock_code, day, exchange_code) for day in complete_days],
                )
        return len(complete_days)

    def latest_venue_date(self, stock_code: str, venue: str) -> dt.date | None:
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._repo._core_schema)
        row = self.conn.execute(
            sql.SQL("SELECT MAX(trade_date)::date AS last_date FROM {} WHERE stock_code=%s AND venue=%s").format(table),
            (stock_code, venue),
        ).fetchone()
        return row["last_date"] if row else None

    def list_venue_trade_dates(self, stock_code: str, venue: str,
                              start: dt.date, end: dt.date) -> set[dt.date]:
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._repo._core_schema)
        rows = self.conn.execute(
            sql.SQL(
                "SELECT DISTINCT trade_date::date AS trade_date FROM {} "
                "WHERE stock_code=%s AND venue=%s AND trade_date::date BETWEEN %s AND %s "
                "ORDER BY trade_date"
            ).format(table),
            (stock_code, venue, start, end),
        ).fetchall()
        return {row["trade_date"] for row in rows if row.get("trade_date") is not None}

    def venue_trade_dates_by_code(self, stock_codes: list[str], venues: tuple[str, ...],
                                  start: dt.date, end: dt.date) -> dict[tuple[str, str], set[dt.date]]:
        if not stock_codes or not venues: return {}
        table = sql.SQL("{}.venue_ohlcv_daily").format(self._repo._core_schema)
        rows = self.conn.execute(
            sql.SQL(
                "SELECT stock_code::text,venue,trade_date::date AS trade_date FROM {} "
                "WHERE stock_code=ANY(%s) AND venue=ANY(%s) "
                "AND trade_date::date BETWEEN %s AND %s GROUP BY 1,2,3"
            ).format(table),
            (stock_codes, list(venues), start, end),
        ).fetchall()
        result: dict[tuple[str, str], set[dt.date]] = {}
        for row in rows:
            key = (str(row["stock_code"]).zfill(6), str(row["venue"]).upper())
            result.setdefault(key, set()).add(row["trade_date"])
        return result

    def upsert_venue_daily(self, stock_code: str, venue: str,
                           rows: list[dict[str, Any]]) -> int:
        records = []
        for row in rows:
            stamp = str(row.get("date") or "").strip()
            try:
                day = pd.to_datetime(stamp, format="%Y%m%d")
            except (TypeError, ValueError):
                continue
            records.append({
                "stock_code": stock_code,
                "trade_date": day,
                "open_price": self._int(row.get("open")),
                "high_price": self._int(row.get("high")),
                "low_price": self._int(row.get("low")),
                "close_price": self._int(row.get("close")),
                "volume": self._int(row.get("jdiff_vol") or row.get("volume")),
                "amount": self._int(row.get("value")) * 1_000_000,
                "source": f"LS_XING32:t8451:{venue}",
            })
        if not records:
            return 0
        frame = pd.DataFrame(records).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        return int(self._repo.upsert_venue_ohlcv(
            frame, venue=venue,
            source_document=f"LS xingAPI t8451 V40 {frame['trade_date'].min():%Y%m%d}-{frame['trade_date'].max():%Y%m%d}",
        ))

    @classmethod
    def _json_dumps(cls, value: Any) -> str:
        """Serialize LS source fields to PostgreSQL jsonb without forbidden NUL characters."""
        return json.dumps(cls._json_safe(value), ensure_ascii=False)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace("\x00", "")
        if isinstance(value, dict):
            return {cls._json_safe(k): cls._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [cls._json_safe(v) for v in value]
        return value

    @staticmethod
    def _num(value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(float(str(value).strip() or 0))
        except (TypeError, ValueError):
            return 0
