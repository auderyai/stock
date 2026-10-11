"""PostgreSQL repository for daily featured-stock source facts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Any, Iterable
import uuid

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import _normalized_conninfo

from .parser import FeaturedRow, ParsedFeaturedSpreadsheet, raw_json_text
from .schema import DDL, SCHEMA_VERSION
from krx_research.theme_research.public_sources import (
    fetch_public_security_names, fetch_public_theme_facts,
)


def _amount(fact: dict[str, Any], source_eok: float | None) -> tuple[Decimal | None, str | None]:
    amount = fact.get("amount")
    if amount is not None and Decimal(amount) > 0:
        return Decimal(amount), "market.ohlcv_daily.amount"
    close = fact.get("close")
    volume = fact.get("volume")
    if close is not None and volume is not None and Decimal(close) > 0 and Decimal(volume) > 0:
        return Decimal(close) * Decimal(volume), "market.ohlcv_daily.close_x_volume"
    if source_eok is not None:
        return Decimal(str(source_eok)) * Decimal("100000000"), "spreadsheet:거래대금(억)"
    return None, None


class FeaturedResearchRepository(AbstractContextManager["FeaturedResearchRepository"]):
    def __init__(self, settings: DataEngineSettings | None = None) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg가 설치되지 않았습니다.")
        self.settings = settings or DataEngineSettings.from_environment()
        self.conn = psycopg.connect(
            _normalized_conninfo(self.settings.conninfo),
            row_factory=dict_row,
            application_name="krx_featured_research",
            autocommit=False,
        )

    def __exit__(self, exc_type: object, _exc: object, _tb: object) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def initialize_schema(self, *, reader_role: str | None = None) -> None:
        with self.conn.transaction():
            for statement in DDL:
                self.conn.execute(statement)
            self.conn.execute(
                """
                INSERT INTO featured_research.schema_meta(key, value)
                VALUES ('schema_version', %s)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                [str(SCHEMA_VERSION)],
            )
            if reader_role:
                role = sql.Identifier(reader_role)
                self.conn.execute(sql.SQL("GRANT USAGE ON SCHEMA featured_research TO {}").format(role))
                self.conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA featured_research TO {}").format(role))
                self.conn.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA featured_research "
                        "GRANT SELECT ON TABLES TO {}"
                    ).format(role)
                )

    def find_batch_by_sha256(self, digest: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM featured_research.import_batches WHERE file_sha256=%s",
            [digest],
        ).fetchone()
        return None if row is None else dict(row)

    def _layout(self, schema: str, table: str) -> set[str]:
        rows = self.conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            """,
            [schema, table],
        ).fetchall()
        return {str(row["column_name"]) for row in rows}

    def _master_mapping(self, rows: Iterable[FeaturedRow], *, include_public: bool = True) -> dict[int, dict[str, Any]]:
        columns = self._layout(self.settings.master_schema, self.settings.master_table)
        ticker_col = next((x for x in ("ticker", "stock_code", "code") if x in columns), None)
        name_col = next((x for x in ("name", "stock_name") if x in columns), None)
        market_col = "market" if "market" in columns else None
        source_rows = list(rows)
        tickers = sorted({row.ticker for row in source_rows if row.ticker})
        names = sorted({row.stock_name for row in source_rows if not row.ticker})
        master_rows: list[dict[str, Any]] = []
        if ticker_col and name_col:
            table = sql.SQL("{}.{}").format(
                sql.Identifier(self.settings.master_schema), sql.Identifier(self.settings.master_table)
            )
            market_expr = sql.SQL("{}::text").format(sql.Identifier(market_col)) if market_col else sql.SQL("NULL::text")
            query = sql.SQL(
                "SELECT {ticker}::text AS ticker, {name}::text AS stock_name, "
                "{market} AS market FROM {table} "
                "WHERE {ticker}::text=ANY(%s::text[]) OR trim({name}::text)=ANY(%s::text[])"
            ).format(
                ticker=sql.Identifier(ticker_col), name=sql.Identifier(name_col),
                market=market_expr, table=table,
            )
            master_rows = [dict(row) for row in self.conn.execute(query, [tickers, names])]
        by_ticker = {str(row["ticker"]).strip().zfill(6): row for row in master_rows}
        by_name: dict[str, dict[str, Any]] = {}
        duplicates: set[str] = set()
        for item in master_rows:
            name = str(item.get("stock_name") or "").strip()
            if name in by_name:
                duplicates.add(name)
            else:
                by_name[name] = item
        for name in duplicates:
            by_name.pop(name, None)
        missing_names = set(names).difference(by_name).difference(duplicates)
        public, _errors = fetch_public_security_names(missing_names) if missing_names and include_public else ({}, [])
        for name, identity in public.items():
            by_name[name] = {
                "ticker": identity["ticker"], "market": identity["market"],
                "market_source": identity["source"],
            }
        result: dict[int, dict[str, Any]] = {}
        for row in source_rows:
            match = by_ticker.get(row.ticker or "") or by_name.get(row.stock_name)
            if match:
                result[row.source_row] = {
                    "ticker": str(match["ticker"]).strip().zfill(6),
                    "market": match.get("market"),
                    "market_source": "market.security_master",
                    "ticker_source": (match.get("market_source") or "market.security_master"),
                }
        return result

    def _market_facts(self, report_date: date, tickers: Iterable[str]) -> dict[str, dict[str, Any]]:
        codes = sorted({str(value).strip().zfill(6) for value in tickers if value})
        if not codes:
            return {}
        columns = self._layout(self.settings.ohlcv_schema, self.settings.ohlcv_table)
        aliases = {
            "ticker": ("ticker", "stock_code"),
            "trade_date": ("trade_date",),
            "close": ("close", "close_price"),
            "volume": ("volume",),
            "amount": ("amount", "trade_value", "value"),
            "market": ("market",),
        }
        layout = {key: next((name for name in values if name in columns), None) for key, values in aliases.items()}
        if any(layout[key] is None for key in ("ticker", "trade_date", "close", "volume")):
            return {}
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self.settings.ohlcv_schema), sql.Identifier(self.settings.ohlcv_table)
        )
        amount_expr = sql.SQL("{}::numeric").format(sql.Identifier(layout["amount"])) if layout["amount"] else sql.SQL("NULL::numeric")
        market_expr = sql.SQL("{}::text").format(sql.Identifier(layout["market"])) if layout["market"] else sql.SQL("NULL::text")
        query = sql.SQL(
            "SELECT {ticker}::text AS ticker, {trade_date}::date AS trade_date, "
            "{close}::numeric AS close, {volume}::numeric AS volume, "
            "{amount} AS amount, {market} AS market FROM {table} "
            "WHERE {trade_date}::date=%s AND {ticker}::text=ANY(%s::text[])"
        ).format(
            ticker=sql.Identifier(layout["ticker"]), trade_date=sql.Identifier(layout["trade_date"]),
            close=sql.Identifier(layout["close"]), volume=sql.Identifier(layout["volume"]),
            amount=amount_expr, market=market_expr, table=table,
        )
        return {
            str(item["ticker"]).strip().zfill(6): dict(item)
            for item in self.conn.execute(query, [report_date, codes])
        }

    def insert_spreadsheet(self, parsed: ParsedFeaturedSpreadsheet) -> tuple[str, int, int]:
        db_only = parsed.sheet_name == "Codex image"
        identities = self._master_mapping(parsed.rows, include_public=not db_only)
        facts = self._market_facts(
            parsed.report_date,
            (identity.get("ticker") or row.ticker
             for row in parsed.rows
             for identity in [identities.get(row.source_row, {})]),
        )
        requested: set[str] = set()
        for row in parsed.rows:
            identity = identities.get(row.source_row, {})
            ticker = identity.get("ticker") or row.ticker
            if not ticker:
                continue
            fact = facts.get(ticker, {})
            amount, _ = _amount(fact, row.source_trading_value_eok)
            if amount is None or not (fact.get("market") or identity.get("market")):
                requested.add(ticker)
        need_values = {
            code for row in parsed.rows
            for code in [identities.get(row.source_row, {}).get("ticker") or row.ticker]
            if code and _amount(facts.get(code, {}), row.source_trading_value_eok)[0] is None
        }
        public, public_errors = (
            fetch_public_theme_facts(parsed.report_date, requested,
                                     naver_tickers=need_values)
            if requested and not db_only else ({}, [])
        )
        batch_id = str(uuid.uuid4())
        matched = sum(
            1 for row in parsed.rows
            if (identity := identities.get(row.source_row, {})).get("ticker") or row.ticker
            if (facts.get(identity.get("ticker") or row.ticker, {}).get("market")
                or identity.get("market")
                or (public.get(identity.get("ticker") or row.ticker)
                    and public[identity.get("ticker") or row.ticker].market))
        )
        unmatched = len(parsed.rows) - matched
        with self.conn.transaction():
            self.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                [f"featured_research:{parsed.report_date.isoformat()}"],
            )
            self.conn.execute(
                "UPDATE featured_research.import_batches SET status='superseded' "
                "WHERE report_date=%s AND status='active'",
                [parsed.report_date],
            )
            self.conn.execute(
                """
                INSERT INTO featured_research.import_batches(
                    batch_id, report_date, file_name, file_sha256, sheet_name,
                    row_count, matched_count, unmatched_count, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active')
                """,
                [batch_id, parsed.report_date, parsed.file_name, parsed.file_sha256,
                 parsed.sheet_name, len(parsed.rows), matched, unmatched],
            )
            for row in parsed.rows:
                identity = identities.get(row.source_row, {})
                ticker = identity.get("ticker") or row.ticker
                fact = facts.get(ticker or "", {})
                trading_value, source = _amount(fact, row.source_trading_value_eok)
                market = fact.get("market") or identity.get("market")
                amount_url = None
                estimated = source == "market.ohlcv_daily.close_x_volume"
                trade_date = fact.get("trade_date")
                public_fact = public.get(ticker) if ticker else None
                if public_fact and public_fact.trade_date == row.report_date:
                    if source is None or source == "spreadsheet:거래대금(억)":
                        if public_fact.trading_value is not None:
                            trading_value = public_fact.trading_value
                            source = public_fact.source
                            amount_url = public_fact.source_url
                            estimated = public_fact.is_estimate
                            trade_date = public_fact.trade_date
                    if not market:
                        market = public_fact.market
                market_source = (
                    "market.ohlcv_daily" if fact.get("market") else
                    identity.get("market_source") if identity.get("market") else
                    public_fact.source if public_fact and public_fact.market else None
                )
                lookup_error = (
                    "종목명으로 코드를 찾지 못했습니다." if not ticker else
                    "기준일 거래대금을 찾지 못했습니다. " + "; ".join(public_errors[:2])
                    if trading_value is None else None
                )
                self.conn.execute(
                    """
                    INSERT INTO featured_research.featured_stocks(
                        batch_id, report_date, source_row, source_ticker, ticker, ticker_source,
                        stock_name, return_pct, source_trading_value_eok, theme_name,
                        reason, db_trade_date, trading_value, trading_value_source,
                        trading_value_source_url, trading_value_is_estimate,
                        market, market_source, lookup_error, public_checked_at,
                        source_file, raw_data
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                              CASE WHEN %s::boolean THEN now() ELSE NULL END,%s,%s::jsonb)
                    """,
                    [batch_id, row.report_date, row.source_row, row.ticker, ticker,
                     ("research_archive" if db_only and row.ticker else
                      "spreadsheet" if row.ticker else identity.get("ticker_source")),
                     row.stock_name, row.return_pct, row.source_trading_value_eok,
                     row.theme_name, row.reason, trade_date, trading_value,
                     source, amount_url, estimated, market, market_source,
                     lookup_error, ticker in requested if ticker else False,
                     parsed.file_name, raw_json_text(row)],
                )
        return batch_id, matched, unmatched

    def available_dates(self) -> list[date]:
        rows = self.conn.execute(
            "SELECT report_date FROM featured_research.import_batches "
            "WHERE status='active' ORDER BY report_date DESC"
        ).fetchall()
        return [row["report_date"] for row in rows]

    def fill_missing_themes(self, start_date: date, end_date: date) -> int:
        """Restore themes from the imported source and dated theme research facts."""

        source_update = self.conn.execute(
            """
            UPDATE featured_research.featured_stocks AS r
            SET theme_name = COALESCE(
                NULLIF(BTRIM(r.raw_data->>'테마 분류'), ''),
                NULLIF(BTRIM(r.raw_data->>'테마'), '')
            )
            FROM featured_research.import_batches AS b
            WHERE b.batch_id=r.batch_id AND b.status='active'
              AND r.report_date BETWEEN %s AND %s
              AND NULLIF(BTRIM(r.theme_name), '') IS NULL
              AND COALESCE(NULLIF(BTRIM(r.raw_data->>'테마 분류'), ''),
                           NULLIF(BTRIM(r.raw_data->>'테마'), '')) IS NOT NULL
            """,
            [start_date, end_date],
        ).rowcount
        theme_available = self.conn.execute(
            "SELECT to_regclass('theme_research.hot_theme_stocks') AS table_name"
        ).fetchone()["table_name"]
        if not theme_available:
            return source_update
        theme_update = self.conn.execute(
            """
            WITH matched AS (
                SELECT r.row_id,
                       string_agg(DISTINCT BTRIM(t.theme_name), ' / '
                                  ORDER BY BTRIM(t.theme_name)) AS themes
                FROM featured_research.featured_stocks AS r
                JOIN featured_research.import_batches AS b
                  ON b.batch_id=r.batch_id AND b.status='active'
                JOIN theme_research.hot_theme_stocks AS t
                  ON t.report_date=r.report_date
                 AND (t.ticker=r.ticker OR
                      ((t.ticker IS NULL OR r.ticker IS NULL)
                       AND t.stock_name=r.stock_name))
                JOIN theme_research.import_batches AS tb
                  ON tb.batch_id=t.batch_id AND tb.status='active'
                WHERE r.report_date BETWEEN %s AND %s
                  AND NULLIF(BTRIM(r.theme_name), '') IS NULL
                GROUP BY r.row_id
            )
            UPDATE featured_research.featured_stocks AS r
            SET theme_name=matched.themes
            FROM matched WHERE matched.row_id=r.row_id
            """,
            [start_date, end_date],
        ).rowcount
        return source_update + theme_update

    def refresh_missing(self, start_date: date, end_date: date) -> dict[str, int]:
        """Backfill missing stored code, market and dated trading value in batches."""

        pending = self.conn.execute(
            """
            SELECT r.row_id, r.report_date, r.ticker, r.stock_name,
                   r.source_trading_value_eok, r.trading_value, r.market
            FROM featured_research.featured_stocks r
            JOIN featured_research.import_batches b ON b.batch_id=r.batch_id
            WHERE b.status='active' AND r.report_date BETWEEN %s AND %s
              AND (r.ticker IS NULL OR r.market IS NULL OR r.trading_value IS NULL)
            ORDER BY r.report_date, r.row_id
            """,
            [start_date, end_date],
        ).fetchall()
        dated: dict[date, list[dict[str, Any]]] = {}
        for record in pending:
            dated.setdefault(record["report_date"], []).append(dict(record))
        result = {"examined": len(pending), "code_updated": 0,
                  "market_updated": 0, "value_updated": 0, "still_missing": 0}
        for report_date, rows in dated.items():
            candidates = [
                FeaturedRow(source_row=int(row["row_id"]), report_date=report_date,
                            ticker=str(row["ticker"]).strip() if row["ticker"] else None,
                            stock_name=str(row["stock_name"]), return_pct=None,
                            source_trading_value_eok=row["source_trading_value_eok"],
                            theme_name=None, reason="", raw_data={})
                for row in rows
            ]
            identities = self._master_mapping(candidates)
            codes = {
                identity.get("ticker") or candidate.ticker
                for candidate in candidates
                for identity in [identities.get(candidate.source_row, {})]
            }
            facts = self._market_facts(report_date, (code for code in codes if code))
            lookup_codes = {
                identity.get("ticker") or candidate.ticker
                for row, candidate in zip(rows, candidates)
                for identity in [identities.get(candidate.source_row, {})]
                if (identity.get("ticker") or candidate.ticker) and
                (not (facts.get(identity.get("ticker") or candidate.ticker, {}).get("market")
                      or identity.get("market")) or
                 (_amount(facts.get(identity.get("ticker") or candidate.ticker, {}),
                          candidate.source_trading_value_eok)[0] is None and
                  row["trading_value"] is None))
            }
            need_value_codes = {
                code for row, candidate in zip(rows, candidates)
                for code in [identities.get(candidate.source_row, {}).get("ticker") or candidate.ticker]
                if code and row["trading_value"] is None and
                _amount(facts.get(code, {}), candidate.source_trading_value_eok)[0] is None
            }
            public, _errors = (
                fetch_public_theme_facts(report_date, lookup_codes,
                                         naver_tickers=need_value_codes)
                if lookup_codes else ({}, [])
            )
            with self.conn.transaction():
                for row, candidate in zip(rows, candidates):
                    identity = identities.get(candidate.source_row, {})
                    code = identity.get("ticker") or candidate.ticker
                    fact = facts.get(code or "", {})
                    amount, source = _amount(fact, candidate.source_trading_value_eok)
                    date_value = fact.get("trade_date")
                    source_url = None
                    estimate = source == "market.ohlcv_daily.close_x_volume"
                    market = fact.get("market") or identity.get("market")
                    public_fact = public.get(code or "")
                    if public_fact and public_fact.trade_date == report_date:
                        if public_fact.trading_value is not None and (amount is None or source == "spreadsheet:거래대금(억)"):
                            amount, source, date_value = (
                                public_fact.trading_value, public_fact.source, public_fact.trade_date
                            )
                            source_url, estimate = public_fact.source_url, public_fact.is_estimate
                        market = market or public_fact.market
                    result["code_updated"] += int(not row["ticker"] and bool(code))
                    result["market_updated"] += int(not row["market"] and bool(market))
                    result["value_updated"] += int(row["trading_value"] is None and amount is not None)
                    result["still_missing"] += int(not code or not market or (row["trading_value"] is None and amount is None))
                    self.conn.execute(
                        """
                        UPDATE featured_research.featured_stocks SET
                            ticker=COALESCE(ticker, %s::char(6)),
                            ticker_source=COALESCE(ticker_source, %s::varchar),
                            db_trade_date=COALESCE(db_trade_date, %s::date),
                            trading_value=COALESCE(trading_value, %s::numeric),
                            trading_value_source=CASE WHEN trading_value IS NULL THEN
                                COALESCE(%s::varchar, trading_value_source) ELSE trading_value_source END,
                            trading_value_source_url=COALESCE(trading_value_source_url, %s::text),
                            trading_value_is_estimate=CASE WHEN trading_value IS NULL AND %s::numeric IS NOT NULL
                                THEN %s::boolean ELSE trading_value_is_estimate END,
                            market=COALESCE(market, %s::varchar),
                            market_source=COALESCE(market_source, %s::varchar),
                            lookup_error=CASE WHEN %s::boolean THEN NULL ELSE lookup_error END,
                            public_checked_at=CASE WHEN %s::boolean THEN now() ELSE public_checked_at END
                        WHERE row_id=%s
                        """,
                        [code, ("spreadsheet" if candidate.ticker else identity.get("ticker_source")),
                         date_value, amount, source, source_url, amount, estimate,
                         market, ("market.ohlcv_daily" if fact.get("market") else
                                  identity.get("market_source") if identity.get("market") else
                                  public_fact.source if public_fact and public_fact.market else None),
                         bool(code and market and (row["trading_value"] is not None or amount is not None)),
                         code in lookup_codes, row["row_id"]],
                    )
        return result

    def query(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT r.report_date, r.ticker, r.ticker_source, r.stock_name, r.return_pct,
                   r.trading_value / 100000000.0 AS trading_value_eok,
                   r.trading_value_source, r.trading_value_source_url,
                   r.trading_value_is_estimate, r.market, r.market_source,
                   r.theme_name, r.reason, r.source_file, r.db_trade_date,
                   r.source_trading_value_eok, r.lookup_error, b.imported_at
            FROM featured_research.featured_stocks r
            JOIN featured_research.import_batches b ON b.batch_id=r.batch_id
            WHERE b.status='active' AND r.report_date BETWEEN %s AND %s
            ORDER BY r.report_date DESC, r.return_pct DESC NULLS LAST, r.stock_name
            """,
            [start_date, end_date],
        ).fetchall()
        return [dict(row) for row in rows]

    def repeated_stocks(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        """Return stocks appearing on at least two distinct report dates."""

        rows = self.conn.execute(
            """
            WITH base AS (
                SELECT r.*,
                       COALESCE(r.ticker, 'NAME:' || trim(r.stock_name)) AS stock_key
                FROM featured_research.featured_stocks r
                JOIN featured_research.import_batches b ON b.batch_id=r.batch_id
                WHERE b.status='active' AND r.report_date BETWEEN %s AND %s
            ), aggregate_rows AS (
                SELECT stock_key,
                       count(DISTINCT report_date) AS appearance_count,
                       array_agg(DISTINCT report_date ORDER BY report_date) AS report_dates,
                       array_remove(array_agg(DISTINCT theme_name ORDER BY theme_name), NULL) AS themes,
                       avg(return_pct) AS average_return_pct,
                       max(return_pct) AS maximum_return_pct
                FROM base
                GROUP BY stock_key
                HAVING count(DISTINCT report_date) >= 2
            ), latest_rows AS (
                SELECT DISTINCT ON (stock_key)
                       stock_key, ticker, stock_name, market, report_date,
                       trading_value / 100000000.0 AS trading_value_eok
                FROM base
                ORDER BY stock_key, report_date DESC, source_row
            )
            SELECT a.appearance_count, l.ticker, l.stock_name, l.market,
                   a.report_dates, a.themes, a.average_return_pct,
                   a.maximum_return_pct, l.report_date AS latest_report_date,
                   l.trading_value_eok
            FROM aggregate_rows a
            JOIN latest_rows l USING (stock_key)
            ORDER BY a.appearance_count DESC, l.stock_name, l.ticker
            """,
            [start_date, end_date],
        ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT min(r.report_date) AS first_date, max(r.report_date) AS last_date,
                   count(DISTINCT r.report_date) AS date_count, count(*) AS row_count,
                   count(r.trading_value) AS value_count, count(r.market) AS market_count
            FROM featured_research.featured_stocks r
            JOIN featured_research.import_batches b ON b.batch_id=r.batch_id
            WHERE b.status='active'
            """
        ).fetchone()
        return dict(row or {})


__all__ = ["FeaturedResearchRepository"]
