"""PostgreSQL repository for daily hot-theme source facts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
import re
from typing import Any, Iterable
import uuid

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:  # Parser and tests can run without the optional DB driver.
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import _normalized_conninfo

from .parser import ParsedSpreadsheet, ThemeRow, raw_json_text
from .public_sources import fetch_public_security_names, fetch_public_theme_facts
from .schema import DDL, SCHEMA_VERSION


def trading_value_from_fact(
    fact: dict[str, Any],
) -> tuple[Decimal | None, str | None]:
    """Prefer the exchange amount and transparently fall back to close*volume."""

    amount = fact.get("amount")
    if amount is not None and Decimal(amount) > 0:
        return Decimal(amount), "market.ohlcv_daily.amount"
    close = fact.get("close")
    volume = fact.get("volume")
    if close is not None and volume is not None and Decimal(close) > 0 and Decimal(volume) > 0:
        return (
            Decimal(close) * Decimal(volume),
            "market.ohlcv_daily.close_x_volume",
        )
    return None, None


class ThemeResearchRepository(AbstractContextManager["ThemeResearchRepository"]):
    def __init__(
        self, settings: DataEngineSettings | None = None, *, read_only: bool = True
    ) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg가 설치되지 않았습니다.")
        self.settings = settings or DataEngineSettings.from_environment()
        self.conn = psycopg.connect(
            _normalized_conninfo(self.settings.conninfo),
            row_factory=dict_row,
            application_name="krx_theme_research",
            autocommit=True,
        )
        if read_only:
            self.conn.execute("SET default_transaction_read_only TO on")
        self.conn.autocommit = False

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
                INSERT INTO theme_research.schema_meta(key, value)
                VALUES ('schema_version', %s)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                [str(SCHEMA_VERSION)],
            )
            if reader_role:
                role = sql.Identifier(reader_role)
                self.conn.execute(sql.SQL("GRANT USAGE ON SCHEMA theme_research TO {}").format(role))
                self.conn.execute(
                    sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA theme_research TO {}").format(role)
                )
                self.conn.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA theme_research "
                        "GRANT SELECT ON TABLES TO {}"
                    ).format(role)
                )

    def find_batch_by_sha256(self, digest: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM theme_research.import_batches WHERE file_sha256=%s",
            [digest],
        ).fetchone()
        return None if row is None else dict(row)

    def _market_layout(self) -> dict[str, str]:
        rows = self.conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            """,
            [self.settings.ohlcv_schema, self.settings.ohlcv_table],
        ).fetchall()
        columns = {str(row["column_name"]) for row in rows}
        aliases = {
            "ticker": ("ticker", "stock_code"),
            "trade_date": ("trade_date",),
            "close": ("close", "close_price"),
            "volume": ("volume",),
            "amount": ("amount", "trade_value", "value"),
            "market": ("market",),
        }
        mapping: dict[str, str] = {}
        for key, candidates in aliases.items():
            found = next((item for item in candidates if item in columns), None)
            if found:
                mapping[key] = found
        missing = [item for item in ("ticker", "trade_date", "close", "volume") if item not in mapping]
        if missing:
            raise RuntimeError(f"market.ohlcv_daily 필수 열이 없습니다: {missing}")
        return mapping

    def _master_layout(self) -> dict[str, str]:
        rows = self.conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            """,
            [self.settings.master_schema, self.settings.master_table],
        ).fetchall()
        columns = {str(row["column_name"]) for row in rows}
        mapping: dict[str, str] = {}
        for key, candidates in {
            "ticker": ("ticker", "stock_code", "code"),
            "name": ("name", "stock_name"),
            "market": ("market",),
        }.items():
            found = next((item for item in candidates if item in columns), None)
            if found:
                mapping[key] = found
        return mapping

    def market_facts(
        self, report_date: date, tickers: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        codes = sorted({str(item).strip().zfill(6) for item in tickers if str(item).strip()})
        if not codes:
            return {}
        layout = self._market_layout()
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self.settings.ohlcv_schema), sql.Identifier(self.settings.ohlcv_table)
        )
        selected_amount = (
            sql.SQL("o.{}::numeric").format(sql.Identifier(layout["amount"]))
            if "amount" in layout
            else sql.SQL("NULL::numeric")
        )
        selected_market = (
            sql.SQL("o.{}::text").format(sql.Identifier(layout["market"]))
            if "market" in layout
            else sql.SQL("NULL::text")
        )
        query = sql.SQL(
            "SELECT o.{ticker}::text AS ticker, o.{trade_date}::date AS trade_date, "
            "o.{close}::numeric AS close, o.{volume}::numeric AS volume, "
            "{amount} AS amount, {market} AS market FROM {table} o "
            "WHERE o.{trade_date}::date=%s AND o.{ticker}::text=ANY(%s::text[])"
        ).format(
            ticker=sql.Identifier(layout["ticker"]),
            trade_date=sql.Identifier(layout["trade_date"]),
            close=sql.Identifier(layout["close"]),
            volume=sql.Identifier(layout["volume"]),
            amount=selected_amount,
            market=selected_market,
            table=table,
        )
        result = {
            str(row["ticker"]).strip().zfill(6): dict(row)
            for row in self.conn.execute(query, [report_date, codes])
        }

        master = self._master_layout()
        if master.get("ticker") and master.get("market"):
            master_table = sql.SQL("{}.{}").format(
                sql.Identifier(self.settings.master_schema), sql.Identifier(self.settings.master_table)
            )
            master_query = sql.SQL(
                "SELECT {ticker}::text AS ticker, {market}::text AS market "
                "FROM {table} WHERE {ticker}::text=ANY(%s::text[])"
            ).format(
                ticker=sql.Identifier(master["ticker"]),
                market=sql.Identifier(master["market"]),
                table=master_table,
            )
            for row in self.conn.execute(master_query, [codes]):
                code = str(row["ticker"]).strip().zfill(6)
                if not result.setdefault(code, {}).get("market"):
                    result[code]["market"] = row["market"]
        return result

    def resolve_identities(self, rows: Iterable[ThemeRow], *, include_public: bool = True) -> tuple[dict[int, dict[str, Any]], list[str]]:
        """Resolve missing codes by exact name, without guessing on duplicates."""

        source_rows = list(rows)
        names = sorted({row.stock_name for row in source_rows if not row.ticker})
        identities: dict[int, dict[str, Any]] = {
            row.source_row: {"ticker": row.ticker, "ticker_source": "spreadsheet"}
            for row in source_rows if row.ticker
        }
        if not names:
            return identities, []
        layout = self._master_layout()
        by_name: dict[str, dict[str, Any]] = {}
        ambiguous: set[str] = set()
        if layout.get("ticker") and layout.get("name"):
            table = sql.SQL("{}.{}").format(
                sql.Identifier(self.settings.master_schema), sql.Identifier(self.settings.master_table)
            )
            market = (
                sql.SQL("{}::text").format(sql.Identifier(layout["market"]))
                if layout.get("market") else sql.SQL("NULL::text")
            )
            query = sql.SQL(
                "SELECT {ticker}::text AS ticker, trim({name}::text) AS stock_name, "
                "{market} AS market FROM {table} WHERE trim({name}::text)=ANY(%s::text[])"
            ).format(ticker=sql.Identifier(layout["ticker"]),
                     name=sql.Identifier(layout["name"]), market=market, table=table)
            for record in self.conn.execute(query, [names]):
                name = str(record["stock_name"]).strip()
                code = str(record["ticker"] or "").strip().zfill(6)
                if not re.fullmatch(r"[0-9A-Z]{6}", code):
                    continue
                if name in by_name and by_name[name]["ticker"] != code:
                    ambiguous.add(name)
                by_name[name] = {"ticker": code, "market": record["market"],
                                 "ticker_source": "market.security_master"}
        for name in ambiguous:
            by_name.pop(name, None)
        unresolved = set(names).difference(by_name).difference(ambiguous)
        public, errors = fetch_public_security_names(unresolved) if unresolved and include_public else ({}, [])
        by_name.update({name: {"ticker": value["ticker"], "market": value["market"],
                               "ticker_source": value["source"]}
                        for name, value in public.items()})
        for row in source_rows:
            if not row.ticker and row.stock_name in by_name:
                identities[row.source_row] = by_name[row.stock_name]
        errors.extend(f"종목명 '{name}'에 해당하는 코드가 여러 개입니다." for name in sorted(ambiguous))
        return identities, errors

    def insert_spreadsheet(self, parsed: ParsedSpreadsheet) -> tuple[str, int, int, int, int]:
        db_only = parsed.sheet_name == "Codex image"
        identities, identity_errors = self.resolve_identities(parsed.rows, include_public=not db_only)
        if db_only:
            for row in parsed.rows:
                if row.ticker and row.source_row in identities:
                    identities[row.source_row]["ticker_source"] = "research_archive"
        codes = {item["ticker"] for item in identities.values()}
        facts = self.market_facts(parsed.report_date, codes)
        missing_amount = {
            code for code in codes if trading_value_from_fact(facts.get(code, {}))[0] is None
        }
        missing_codes = missing_amount | {
            identity["ticker"] for identity in identities.values()
            if not (facts.get(identity["ticker"], {}).get("market") or identity.get("market"))
        }
        public, public_errors = (
            fetch_public_theme_facts(
                parsed.report_date, missing_codes, include_naver=bool(missing_amount)
            )
            if missing_codes and not db_only else ({}, [])
        )
        batch_id = str(uuid.uuid4())
        matched = 0
        resolved = 0
        prepared: list[tuple[ThemeRow, dict[str, Any], dict[str, Any]]] = []
        for row in parsed.rows:
            identity = identities.get(row.source_row, {})
            ticker = identity.get("ticker")
            if ticker and not row.ticker:
                resolved += 1
            fact = facts.get(ticker, {}) if ticker else {}
            amount, source = trading_value_from_fact(fact)
            market = fact.get("market") or identity.get("market")
            source_url = None
            is_estimate = source == "market.ohlcv_daily.close_x_volume"
            trade_date = fact.get("trade_date")
            public_fact = public.get(ticker) if ticker else None
            if amount is None and public_fact and public_fact.trade_date == parsed.report_date:
                amount = public_fact.trading_value
                if amount is not None:
                    source = public_fact.source
                    source_url = public_fact.source_url
                    is_estimate = public_fact.is_estimate
                    trade_date = public_fact.trade_date
            if not market and public_fact and public_fact.trade_date == parsed.report_date:
                market = public_fact.market
            if amount is None and row.source_trading_value_eok is not None:
                amount = Decimal(str(row.source_trading_value_eok)) * Decimal("100000000")
                source = "spreadsheet:거래대금(억)"
            if amount is not None:
                matched += 1
            lookup_error = None
            if not ticker:
                lookup_error = "종목명으로 종목코드를 확인하지 못했습니다. " + "; ".join(identity_errors[:3])
            elif amount is None:
                lookup_error = "기준일 거래대금을 확인하지 못했습니다. " + "; ".join(public_errors[:3])
            prepared.append((row, identity, {
                "trade_date": trade_date, "amount": amount, "source": source,
                "source_url": source_url, "is_estimate": is_estimate,
                "market": market,
                "market_source": "market.ohlcv_daily" if fact.get("market") else
                (identity.get("ticker_source") if identity.get("market") else
                 (public_fact.source if public_fact and public_fact.market else None)),
                "lookup_error": lookup_error,
                "public_checked": ticker in missing_codes if ticker else False,
            }))
        unmatched = len(parsed.rows) - matched
        with self.conn.transaction():
            self.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                [f"theme_research:{parsed.report_date.isoformat()}"],
            )
            self.conn.execute(
                """
                UPDATE theme_research.import_batches SET status='superseded'
                WHERE report_date=%s AND status='active'
                """,
                [parsed.report_date],
            )
            self.conn.execute(
                """
                INSERT INTO theme_research.import_batches(
                    batch_id, report_date, file_name, file_sha256, sheet_name,
                    row_count, matched_count, unmatched_count, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active')
                """,
                [batch_id, parsed.report_date, parsed.file_name, parsed.file_sha256,
                 parsed.sheet_name, len(parsed.rows), matched, unmatched],
            )
            for row, identity, values in prepared:
                self._insert_row(batch_id, parsed, row, identity, values)
        return batch_id, matched, unmatched, resolved, sum(not identity.get("ticker") for _, identity, _ in prepared)

    def _insert_row(
        self,
        batch_id: str,
        parsed: ParsedSpreadsheet,
        row: ThemeRow,
        identity: dict[str, Any],
        values: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO theme_research.hot_theme_stocks(
                batch_id, report_date, source_row, theme_name, ticker, ticker_source, stock_name,
                return_pct, reason, source_trading_value_eok, db_trade_date,
                trading_value, trading_value_source, trading_value_source_url,
                trading_value_is_estimate, market, market_source, public_checked_at,
                lookup_error, source_file, raw_data
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      CASE WHEN %s::boolean THEN now() ELSE NULL END,%s,%s,%s::jsonb)
            """,
            [batch_id, row.report_date, row.source_row, row.theme_name, identity.get("ticker"),
             identity.get("ticker_source"),
            row.stock_name, row.return_pct, row.reason, row.source_trading_value_eok,
             values["trade_date"], values["amount"], values["source"],
             values["source_url"], values["is_estimate"], values["market"],
             values["market_source"], values["public_checked"], values["lookup_error"],
             parsed.file_name, raw_json_text(row)],
        )

    def available_dates(self) -> list[date]:
        rows = self.conn.execute(
            """
            SELECT report_date FROM theme_research.import_batches
            WHERE status='active' ORDER BY report_date DESC
            """
        ).fetchall()
        return [row["report_date"] for row in rows]

    def refresh_trading_values(
        self,
        start_date: date,
        end_date: date,
        *,
        only_missing: bool = True,
        include_public: bool = False,
    ) -> dict[str, int]:
        """Reconnect active theme rows to exact-date facts in market.ohlcv_daily."""

        condition = (
            "AND (r.ticker IS NULL OR r.trading_value IS NULL OR nullif(trim(r.market), '') IS NULL)"
            if only_missing else ""
        )
        rows = self.conn.execute(
            f"""
            SELECT r.row_id, r.report_date, r.ticker::text AS ticker,
                   r.stock_name, r.trading_value, r.market
            FROM theme_research.hot_theme_stocks r
            JOIN theme_research.import_batches b ON b.batch_id=r.batch_id
            WHERE b.status='active' AND r.report_date BETWEEN %s AND %s
              {condition}
            ORDER BY r.report_date, r.row_id
            """,
            [start_date, end_date],
        ).fetchall()
        by_date: dict[date, list[dict[str, Any]]] = {}
        for row in rows:
            by_date.setdefault(row["report_date"], []).append(dict(row))

        updated = 0
        market_updated = 0
        krx_updated = 0
        naver_updated = 0
        code_updated = 0
        patches: list[dict[str, Any]] = []
        lookup_errors: list[str] = []
        for report_date, dated_rows in by_date.items():
            missing_identity_rows = [
                ThemeRow(
                    source_row=int(row["row_id"]), report_date=report_date, ticker=None,
                    stock_name=str(row["stock_name"]), return_pct=None,
                    source_trading_value_eok=None, theme_name="", reason="", raw_data={},
                )
                for row in dated_rows if not row["ticker"]
            ]
            identities, errors = self.resolve_identities(missing_identity_rows)
            lookup_errors.extend(errors)
            facts = self.market_facts(
                report_date,
                (str(row["ticker"]).strip() if row["ticker"] else
                 identities.get(int(row["row_id"]), {}).get("ticker", "") for row in dated_rows),
            )
            unresolved: list[str] = []
            for row in dated_rows:
                identity = identities.get(int(row["row_id"]), {})
                raw_code = str(row["ticker"] or identity.get("ticker") or "").strip()
                code = raw_code.zfill(6) if raw_code.isdigit() else raw_code.upper()
                if not re.fullmatch(r"[0-9A-Z]{6}", code):
                    code = ""
                fact = facts.get(code, {})
                amount, amount_source = trading_value_from_fact(fact)
                patch = {
                    "row": row,
                    "ticker": code or None,
                    "ticker_source": identity.get("ticker_source"),
                    "trade_date": fact.get("trade_date"),
                    "amount": amount,
                    "amount_source": amount_source,
                    "source_url": None,
                    "is_estimate": amount_source == "market.ohlcv_daily.close_x_volume",
                    "market": fact.get("market") or identity.get("market"),
                    "market_source": ("market.ohlcv_daily" if fact.get("market") else
                                      identity.get("ticker_source") if identity.get("market") else None),
                    "error": None,
                }
                patches.append(patch)
                if code and (amount is None or not patch["market"]):
                    unresolved.append(code)
            if include_public and unresolved:
                public, errors = fetch_public_theme_facts(report_date, unresolved)
                lookup_errors.extend(errors)
                for patch in patches:
                    row = patch["row"]
                    if row["report_date"] != report_date:
                        continue
                    code = patch["ticker"]
                    public_fact = public.get(code)
                    if public_fact is None:
                        continue
                    if patch["amount"] is None and public_fact.trading_value is not None:
                        patch["trade_date"] = public_fact.trade_date
                        patch["amount"] = public_fact.trading_value
                        patch["amount_source"] = public_fact.source
                        patch["source_url"] = public_fact.source_url
                        patch["is_estimate"] = public_fact.is_estimate
                    if not patch["market"] and public_fact.market:
                        patch["market"] = public_fact.market
                        patch["market_source"] = public_fact.source

        with self.conn.transaction():
            for patch in patches:
                row = patch["row"]
                old_amount = row.get("trading_value")
                old_market = str(row.get("market") or "").strip()
                new_amount = patch["amount"] if patch["amount"] is not None else old_amount
                new_market = patch["market"] or old_market or None
                if old_amount is None and new_amount is not None:
                    updated += 1
                    source_text = str(patch["amount_source"] or "")
                    if source_text.startswith("NAVER:"):
                        naver_updated += 1
                    elif "KRX" in source_text or source_text == "pykrx":
                        krx_updated += 1
                if not old_market and new_market:
                    market_updated += 1
                if not row["ticker"] and patch["ticker"]:
                    code_updated += 1
                self.conn.execute(
                    """
                    UPDATE theme_research.hot_theme_stocks
                    SET ticker=COALESCE(%s::char(6), ticker),
                        ticker_source=COALESCE(%s::varchar, ticker_source),
                        db_trade_date=COALESCE(%s::date, db_trade_date),
                        trading_value=COALESCE(%s::numeric, trading_value),
                        trading_value_source=COALESCE(%s::varchar, trading_value_source),
                        trading_value_source_url=COALESCE(%s::text, trading_value_source_url),
                        trading_value_is_estimate=CASE WHEN %s::numeric IS NULL
                            THEN trading_value_is_estimate ELSE %s::boolean END,
                        market=COALESCE(%s::varchar, market),
                        market_source=COALESCE(%s::varchar, market_source),
                        lookup_error=CASE WHEN %s::boolean THEN NULL ELSE lookup_error END,
                        public_checked_at=CASE WHEN %s::boolean THEN now() ELSE public_checked_at END
                    WHERE row_id=%s
                    """,
                    [
                        patch["ticker"], patch["ticker_source"],
                        patch["trade_date"], patch["amount"], patch["amount_source"],
                        patch["source_url"], patch["amount"], patch["is_estimate"],
                        patch["market"], patch["market_source"],
                        patch["ticker"] is not None and new_amount is not None,
                        include_public,
                        row["row_id"],
                    ],
                )
            self.conn.execute(
                """
                UPDATE theme_research.import_batches b
                SET matched_count=s.matched_count,
                    unmatched_count=b.row_count-s.matched_count
                FROM (
                    SELECT batch_id, count(trading_value)::integer AS matched_count
                    FROM theme_research.hot_theme_stocks
                    GROUP BY batch_id
                ) s
                WHERE b.batch_id=s.batch_id AND b.status='active'
                  AND b.report_date BETWEEN %s AND %s
                """,
                [start_date, end_date],
            )
        return {
            "examined": len(rows),
            "updated": updated,
            "code_updated": code_updated,
            "market_updated": market_updated,
            "krx_updated": krx_updated,
            "naver_updated": naver_updated,
            "missing": sum(1 for patch in patches if patch["amount"] is None and patch["row"].get("trading_value") is None),
            "code_missing": sum(1 for patch in patches if not patch["ticker"]),
            "market_missing": sum(1 for patch in patches if not (patch["market"] or patch["row"].get("market"))),
            "source_errors": len(lookup_errors),
        }

    def query(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT r.report_date, r.theme_name, r.ticker, r.ticker_source, r.stock_name,
                   r.return_pct, r.trading_value,
                   COALESCE(r.trading_value / 100000000.0,
                            r.source_trading_value_eok) AS trading_value_eok,
                   CASE WHEN r.trading_value IS NOT NULL THEN r.trading_value_source
                        WHEN r.source_trading_value_eok IS NOT NULL
                        THEN 'spreadsheet:거래대금(억)'
                   END AS trading_value_source,
                   r.trading_value_source_url,
                   r.trading_value_is_estimate, r.market, r.market_source,
                   r.reason, r.source_file,
                   r.db_trade_date, r.source_trading_value_eok, r.lookup_error, b.imported_at
            FROM theme_research.hot_theme_stocks r
            JOIN theme_research.import_batches b ON b.batch_id=r.batch_id
            WHERE b.status='active' AND r.report_date BETWEEN %s AND %s
            ORDER BY r.report_date DESC, r.theme_name, r.return_pct DESC NULLS LAST,
                     r.ticker
            """,
            [start_date, end_date],
        ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT min(report_date) AS first_date, max(report_date) AS last_date,
                   count(DISTINCT report_date) AS date_count, count(*) AS row_count,
                   count(trading_value) AS value_count
            FROM theme_research.hot_theme_stocks r
            WHERE EXISTS (
                SELECT 1 FROM theme_research.import_batches b
                WHERE b.batch_id=r.batch_id AND b.status='active'
            )
            """
        ).fetchone()
        return dict(row or {})


__all__ = ["ThemeResearchRepository", "trading_value_from_fact"]
