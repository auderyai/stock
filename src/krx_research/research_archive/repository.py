from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import sql

from krx_research.database import open_research_store
from .models import ParsedResearchSource, SourceObservation
from .schema import DDL, SCHEMA_VERSION


class ResearchArchiveRepository(AbstractContextManager["ResearchArchiveRepository"]):
    """Persists source evidence separately from Stock DB-authoritative facts."""

    def __init__(self, database_target, *, read_only: bool = False):
        self.store = open_research_store(database_target, read_only=read_only)
        self.conn = self.store.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        self.store.close()

    def initialize_schema(self, *, reader_role: str | None = None) -> None:
        with self.conn.transaction():
            for statement in DDL:
                self.conn.execute(statement)
            self.conn.execute(
                "INSERT INTO research_archive.schema_meta(key,value) VALUES('schema_version',%s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", [str(SCHEMA_VERSION)],
            )
            if reader_role:
                role = sql.Identifier(reader_role)
                self.conn.execute(sql.SQL("GRANT USAGE ON SCHEMA research_archive TO {}").format(role))
                self.conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA research_archive TO {}").format(role))

    def by_sha256(self, digest: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM research_archive.documents WHERE sha256=%s", [digest]
        ).fetchone()
        return dict(row) if row else None

    def insert(self, parsed: ParsedResearchSource, *, digest: str, canonical_path: str,
               mime_type: str, file_size: int) -> str:
        existing = self.by_sha256(digest)
        if existing:
            return str(existing["document_id"])
        identities = self._identities(parsed.observations)
        facts = self._facts(parsed.report_date, parsed.observations, identities)
        document_id = str(uuid.uuid4())
        with self.conn.transaction():
            self.conn.execute(
                """INSERT INTO research_archive.documents(
                    document_id,sha256,document_kind,report_date,ticker,company_name,title,
                    provider,original_filename,canonical_path,mime_type,file_size,
                    extraction_status,metadata)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                [document_id, digest, parsed.kind, parsed.report_date, parsed.ticker,
                 parsed.company_name or None, parsed.title, parsed.provider or None,
                 parsed.path.name, canonical_path, mime_type, file_size,
                 "EXTRACTED", json.dumps(parsed.metadata, ensure_ascii=False, default=str)],
            )
            for number, page in enumerate(parsed.pages, 1):
                self.conn.execute(
                    "INSERT INTO research_archive.pages(document_id,page_number,page_text) "
                    "VALUES(%s,%s,%s)", [document_id, number, page],
                )
            for order, observation in enumerate(parsed.observations, 1):
                identity = identities.get(order, {})
                ticker = identity.get("ticker") or observation.ticker
                fact = facts.get(ticker or "", {})
                amount = fact.get("amount")
                if amount is None and fact.get("close") is not None and fact.get("volume") is not None:
                    amount = Decimal(fact["close"]) * Decimal(fact["volume"])
                authority = "DB_AUTHORITY" if fact else ("SOURCE_ONLY" if ticker else "UNRESOLVED")
                self.conn.execute(
                    """INSERT INTO research_archive.observations(
                        document_id,source_order,category,source_ticker,ticker,stock_name,reason,
                        source_return_pct,source_trading_value_eok,db_trade_date,db_return_pct,
                        db_trading_value_eok,db_close,market,authority,raw_data)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    [document_id, order, observation.category or None, observation.ticker,
                     ticker, identity.get("stock_name") or observation.stock_name,
                     observation.reason or None, observation.source_return_pct,
                     observation.source_trading_value_eok, fact.get("trade_date"),
                     fact.get("return_pct"),
                     (Decimal(amount) / Decimal("100000000") if amount is not None else None),
                     fact.get("close"), fact.get("market") or identity.get("market"),
                     authority, json.dumps(observation.raw, ensure_ascii=False, default=str)],
                )
        return document_id

    def query(self, start: date, end: date, search: str = "") -> list[dict[str, Any]]:
        pattern = f"%{search.strip()}%"
        rows = self.conn.execute(
            """SELECT d.report_date,d.document_kind,d.title,d.provider,d.ticker AS document_ticker,
                      d.company_name,d.original_filename,d.canonical_path,
                      o.source_order,o.category,o.ticker,o.stock_name,o.reason,
                      o.source_return_pct,o.db_return_pct,
                      o.source_trading_value_eok,o.db_trading_value_eok,o.db_close,o.market,o.authority
                 FROM research_archive.documents d
                 LEFT JOIN research_archive.observations o USING(document_id)
                WHERE d.report_date BETWEEN %s AND %s
                  AND (%s='' OR d.title ILIKE %s OR COALESCE(d.company_name,'') ILIKE %s
                       OR COALESCE(o.stock_name,'') ILIKE %s OR COALESCE(o.ticker,'') ILIKE %s
                       OR COALESCE(o.reason,'') ILIKE %s)
                ORDER BY d.report_date DESC,d.imported_at DESC,o.source_order""",
            [start, end, search.strip(), pattern, pattern, pattern, pattern, pattern],
        ).fetchall()
        return [dict(row) for row in rows]

    def search_text(self, query: str, limit: int = 50,
                    period: tuple[date, date] | None = None) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        date_clause = " AND d.report_date BETWEEN %s AND %s" if period else ""
        params = [pattern, pattern, pattern, pattern]
        if period:
            params.extend(period)
        params.append(int(limit))
        rows = self.conn.execute(
            f"""SELECT d.report_date,d.document_kind,d.ticker,d.company_name,d.title,d.provider,
                      d.canonical_path,p.page_number,left(p.page_text,1200) AS excerpt
                 FROM research_archive.documents d
                 LEFT JOIN research_archive.pages p USING(document_id)
                WHERE (d.title ILIKE %s OR COALESCE(d.company_name,'') ILIKE %s
                   OR COALESCE(d.ticker,'') ILIKE %s OR COALESCE(p.page_text,'') ILIKE %s)
                   {date_clause}
                ORDER BY d.report_date DESC,p.page_number LIMIT %s""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def document_observations(self, document_ids: list[str]) -> list[dict[str, Any]]:
        """Return source and Stock-DB facts for an explicit set of archived documents."""
        if not document_ids:
            return []
        rows = self.conn.execute(
            """SELECT d.document_id::text,d.sha256,d.report_date,d.original_filename,
                      o.source_order,o.category,o.source_ticker,o.ticker,o.stock_name,o.reason,
                      o.source_return_pct,o.source_trading_value_eok,o.db_trade_date,
                      o.db_return_pct,o.db_trading_value_eok,o.market,o.authority,o.raw_data
                 FROM research_archive.documents d
                 JOIN research_archive.observations o USING(document_id)
                WHERE d.document_id=ANY(%s::uuid[])
                ORDER BY d.report_date,d.imported_at,o.source_order""",
            [document_ids],
        ).fetchall()
        return [dict(row) for row in rows]

    def reconciled_document_observations(
        self, document_ids: list[str], report_date: date,
    ) -> list[dict[str, Any]]:
        """Re-evaluate archived source facts against Stock DB for the selected input date."""
        records = self.document_observations(document_ids)
        observations = tuple(SourceObservation(
            stock_name=str(row["stock_name"]), ticker=row.get("source_ticker") or row.get("ticker"),
            category=str(row.get("category") or ""), reason=str(row.get("reason") or ""),
            source_return_pct=row.get("source_return_pct"),
            source_trading_value_eok=row.get("source_trading_value_eok"),
            raw=dict(row.get("raw_data") or {}),
        ) for row in records)
        identities = self._identities(observations)
        facts = self._facts(report_date, observations, identities)
        reconciled: list[dict[str, Any]] = []
        for order, (record, observation) in enumerate(zip(records, observations), 1):
            identity = identities.get(order, {})
            ticker = identity.get("ticker") or observation.ticker
            fact = facts.get(ticker or "", {})
            amount = fact.get("amount")
            if amount is None and fact.get("close") is not None and fact.get("volume") is not None:
                amount = Decimal(fact["close"]) * Decimal(fact["volume"])
            reconciled.append({
                **record, "report_date": report_date, "ticker": ticker,
                "stock_name": identity.get("stock_name") or observation.stock_name,
                "db_trade_date": fact.get("trade_date"), "db_return_pct": fact.get("return_pct"),
                "db_trading_value_eok": (Decimal(amount) / Decimal("100000000") if amount is not None else None),
                "market": fact.get("market") or identity.get("market"),
                "authority": "DB_AUTHORITY" if fact else ("SOURCE_ONLY" if ticker else "UNRESOLVED"),
            })
        return reconciled

    def _layout(self, schema: str, table: str) -> set[str]:
        return {str(row["column_name"]) for row in self.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s", [schema, table]
        ).fetchall()}

    def _identities(self, observations: tuple[SourceObservation, ...]) -> dict[int, dict[str, Any]]:
        columns = self._layout("market", "security_master")
        ticker_col = next((x for x in ("ticker", "stock_code", "code") if x in columns), None)
        name_col = next((x for x in ("name", "stock_name") if x in columns), None)
        if not ticker_col or not name_col or not observations:
            return {}
        tickers = [str(x.ticker).zfill(6) for x in observations if x.ticker]
        names = [x.stock_name.strip() for x in observations if x.stock_name]
        table = sql.SQL("{}.{}").format(sql.Identifier("market"), sql.Identifier("security_master"))
        market = sql.SQL("market::text") if "market" in columns else sql.SQL("NULL::text")
        query = sql.SQL("SELECT {t}::text ticker,{n}::text stock_name,{m} market FROM {table} "
                        "WHERE {t}::text=ANY(%s::text[]) OR trim({n}::text)=ANY(%s::text[])").format(
            t=sql.Identifier(ticker_col), n=sql.Identifier(name_col), m=market, table=table)
        found = [dict(row) for row in self.conn.execute(query, [tickers, names])]
        by_code = {str(row["ticker"]).strip().zfill(6): row for row in found}
        by_name = {str(row["stock_name"]).strip(): row for row in found}
        return {i: (by_code.get(str(item.ticker).zfill(6)) if item.ticker else None)
                   or by_name.get(item.stock_name.strip()) or {}
                for i, item in enumerate(observations, 1)}

    def _facts(self, report_date: date, observations, identities) -> dict[str, dict[str, Any]]:
        codes = sorted({str(identities.get(i, {}).get("ticker") or item.ticker or "").strip().zfill(6)
                        for i, item in enumerate(observations, 1)
                        if identities.get(i, {}).get("ticker") or item.ticker})
        if not codes:
            return {}
        columns = self._layout("market", "ohlcv_daily")
        aliases = {"ticker": ("ticker", "stock_code"), "date": ("trade_date",),
                   "close": ("close", "close_price"), "volume": ("volume",),
                   "amount": ("amount", "trade_value", "value"),
                   "return_pct": ("change_rate", "change_ratio"), "market": ("market",)}
        c = {key: next((x for x in values if x in columns), None) for key, values in aliases.items()}
        if not all(c[x] for x in ("ticker", "date", "close", "volume")):
            return {}
        table = sql.SQL("market.ohlcv_daily")
        expr = lambda key, cast: (sql.SQL("{}::" + cast).format(sql.Identifier(c[key]))
                                  if c[key] else sql.SQL("NULL::" + cast))
        query = sql.SQL(
            "SELECT {t}::text ticker,{d}::date trade_date,{close} close,{volume} volume,"
            "{amount} amount,{ret} return_pct,{market} market FROM {table} "
            "WHERE {d}::date=%s AND {t}::text=ANY(%s::text[])"
        ).format(t=sql.Identifier(c["ticker"]), d=sql.Identifier(c["date"]),
                 close=expr("close", "numeric"), volume=expr("volume", "numeric"),
                 amount=expr("amount", "numeric"), ret=expr("return_pct", "numeric"),
                 market=expr("market", "text"), table=table)
        return {str(row["ticker"]).strip().zfill(6): dict(row)
                for row in self.conn.execute(query, [report_date, codes])}
