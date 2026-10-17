from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from datetime import date

import pandas as pd

from krx_research.database import open_research_store
from .schema import DDL, SCHEMA_VERSION


class ChartLearningRepository(AbstractContextManager["ChartLearningRepository"]):
    """The only PostgreSQL boundary for chart-learning samples and OHLCV facts."""

    def __init__(self, database_target):
        self.store = open_research_store(database_target)
        self.conn = self.store.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        self.store.close()

    def initialize(self) -> None:
        with self.conn.transaction():
            for statement in DDL:
                self.conn.execute(statement)
            self.conn.execute(
                "INSERT INTO chart_learning.schema_meta(key,value) VALUES('schema_version',%s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", [str(SCHEMA_VERSION)],
            )

    def resolve(self, ticker: str, company_name: str) -> dict:
        name = company_name.strip()
        key, value = ("btrim(ticker)", ticker) if ticker else ("name", name)
        rows = self.conn.execute(
            "SELECT btrim(ticker) ticker,COALESCE(name,'') company_name "
            f"FROM market.security_master WHERE {key}=%s ORDER BY ticker LIMIT 2", [value],
        ).fetchall()
        if not rows:
            raise ValueError(f"Stock DB에서 종목을 찾을 수 없습니다: {ticker or name}")
        if len(rows) > 1:
            raise ValueError(f"동일한 종목명이 여러 개입니다. 종목코드를 입력하십시오: {name}")
        result = dict(rows[0])
        if company_name.strip() and company_name.strip() != result["company_name"]:
            raise ValueError(
                f"종목명과 DB가 일치하지 않습니다: 입력={company_name}, DB={result['company_name']}"
            )
        return result

    def history(self, ticker: str, end: date, limit: int = 1000) -> pd.DataFrame:
        rows = self.conn.execute(
            "SELECT trade_date::date trade_date,open::double precision open,"
            "high::double precision high,low::double precision low,close::double precision close,"
            "volume::double precision volume FROM market.ohlcv_daily "
            "WHERE btrim(ticker)=%s AND trade_date::date<=%s "
            "ORDER BY trade_date::date DESC LIMIT %s",
            [ticker, end, int(limit)],
        ).fetchall()
        frame = pd.DataFrame([dict(row) for row in reversed(rows)])
        if frame.empty:
            raise ValueError(f"Stock DB에 {ticker}의 주가·거래량 자료가 없습니다.")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        return frame

    def market_context(self, codes: tuple[str, ...], end: date,
                       limit_per_index: int = 1000) -> pd.DataFrame:
        rows = self.conn.execute(
            "WITH ranked AS (SELECT index_code,trade_date::date trade_date,"
            "close_price::double precision close_price,"
            "row_number() OVER(PARTITION BY index_code ORDER BY trade_date DESC) rn "
            "FROM market_core.index_ohlcv_daily WHERE index_code=ANY(%s) AND trade_date<=%s) "
            "SELECT index_code,trade_date,close_price FROM ranked WHERE rn<=%s "
            "ORDER BY index_code,trade_date",
            [list(codes), end, int(limit_per_index)],
        ).fetchall()
        frame = pd.DataFrame([dict(row) for row in rows])
        if frame.empty or set(frame.get("index_code", ())) != set(codes):
            raise ValueError("KOSPI·KOSDAQ 종합지수 DB 자료가 모두 준비되지 않았습니다.")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        return frame

    def save(self, *, digest: str, ticker: str, company_name: str, start: date, end: date,
             db_reference_date: date, canonical_path: str, assessment: str, rationale: str,
             policy: dict, features: dict) -> tuple[str, bool]:
        existing = self.conn.execute(
            "SELECT sample_id FROM chart_learning.pattern_samples "
            "WHERE sha256=%s AND ticker=%s AND pattern_start=%s AND pattern_end=%s",
            [digest, ticker, start, end],
        ).fetchone()
        if existing:
            with self.conn.transaction():
                self.conn.execute(
                    "UPDATE chart_learning.pattern_samples SET db_reference_date=%s,"
                    "assessment=%s,rationale=%s,policy_version=%s,policy=%s::jsonb,features=%s::jsonb "
                    "WHERE sample_id=%s",
                    [db_reference_date, assessment, rationale, int(policy["version"]),
                     json.dumps(policy, ensure_ascii=False),
                     json.dumps(features, ensure_ascii=False, default=str), existing["sample_id"]],
                )
            return str(existing["sample_id"]), True
        sample_id = str(uuid.uuid4())
        with self.conn.transaction():
            self.conn.execute(
                """INSERT INTO chart_learning.pattern_samples(
                    sample_id,sha256,ticker,company_name,pattern_start,pattern_end,
                    db_reference_date,canonical_path,assessment,rationale,policy_version,policy,features)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                [sample_id, digest, ticker, company_name, start, end, db_reference_date,
                 canonical_path, assessment, rationale, int(policy["version"]),
                 json.dumps(policy, ensure_ascii=False),
                 json.dumps(features, ensure_ascii=False, default=str)],
            )
        return sample_id, False
