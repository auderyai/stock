from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as calendar_date
from time import perf_counter

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings
from krx_research_nextgen.models.screening import (
    ScreeningKind,
    ScreeningQuery,
    ScreeningResult,
)


@dataclass(frozen=True)
class _Relation:
    schema: str
    table: str
    columns: dict[str, str]


class ScreeningRepository:
    """Read-only PostgreSQL screener repository optimized for date-scoped scans."""

    _OHLCV_ALIASES = {
        "stock_code": ("stock_code", "ticker"),
        "trade_date": ("trade_date",),
        "open": ("open_price", "open"),
        "high": ("high_price", "high"),
        "low": ("low_price", "low"),
        "close": ("close_price", "close"),
        "volume": ("volume",),
        "trading_value": ("trading_value", "trade_value", "amount", "turnover"),
        "change_rate": ("change_ratio", "change_rate"),
    }
    _MASTER_ALIASES = {
        "stock_code": ("stock_code", "ticker", "code"),
        "stock_name": ("stock_name", "name"),
        "market": ("market", "market_name", "market_type"),
        "is_spac": ("is_spac", "spac"),
        "industry": ("industry", "sector", "industry_name"),
        "market_cap": ("market_cap", "market_capitalization"),
        "shares": ("shares", "listed_shares", "shares_outstanding"),
    }

    def __init__(self, settings: PostgreSQLSettings | None = None) -> None:
        self._settings = settings or PostgreSQLSettings.from_c_stock_env()
        self._conn = psycopg.connect(
            **self._settings.connect_kwargs(),
            row_factory=dict_row,
            autocommit=True,
            application_name="krx_nextgen_stage4_sql_perf",
        )
        self._ohlcv = self._resolve_ohlcv()
        self._master = self._resolve_master()
        self.last_metrics: dict[str, float | str | int | bool] = {}
        self._trade_date_cache: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.close()

    def _relation_columns(self, schema: str, table: str) -> set[str]:
        rows = self._conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (schema, table),
        ).fetchall()
        return {str(r["column_name"]) for r in rows}

    @staticmethod
    def _map(columns: set[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
        out: dict[str, str] = {}
        for canonical, choices in aliases.items():
            hit = next((c for c in choices if c in columns), None)
            if hit:
                out[canonical] = hit
        return out

    def _find(self, names: list[str]) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog','information_schema')
              AND table_type IN ('BASE TABLE','FOREIGN')
              AND table_name = ANY(%s::text[])
            ORDER BY CASE WHEN table_schema='market' THEN 0
                          WHEN table_schema='public' THEN 1 ELSE 2 END,
                     table_schema, table_name
            """,
            (names,),
        ).fetchall()
        return [(str(r["table_schema"]), str(r["table_name"])) for r in rows]

    def _resolve_ohlcv(self) -> _Relation:
        pairs = self._find(["ohlcv_daily"])
        required = {"stock_code","trade_date","high","close","volume"}
        for schema, table in pairs:
            mapped = self._map(self._relation_columns(schema, table), self._OHLCV_ALIASES)
            if required.issubset(mapped):
                return _Relation(schema, table, mapped)
        raise RuntimeError("Compatible OHLCV relation not found.")

    def _resolve_master(self) -> _Relation:
        pairs = self._find(["security_master","securities"])
        required = {"stock_code","stock_name"}
        for schema, table in pairs:
            mapped = self._map(self._relation_columns(schema, table), self._MASTER_ALIASES)
            if required.issubset(mapped):
                return _Relation(schema, table, mapped)
        raise RuntimeError("Compatible security master relation not found.")

    @property
    def ohlcv_relation(self) -> str:
        return f"{self._ohlcv.schema}.{self._ohlcv.table}"

    @property
    def master_relation(self) -> str:
        return f"{self._master.schema}.{self._master.table}"

    def latest_trade_date(self) -> str:
        c = self._ohlcv.columns
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self._ohlcv.schema),
            sql.Identifier(self._ohlcv.table),
        )
        q = sql.SQL("SELECT max({d})::date AS d FROM {t}").format(
            d=sql.Identifier(c["trade_date"]),
            t=table,
        )
        row = self._conn.execute(q).fetchone()
        if not row or not row["d"]:
            raise RuntimeError("OHLCV table has no trade date.")
        return str(row["d"])

    def earliest_trade_date(self) -> str:
        c = self._ohlcv.columns
        table = sql.SQL("{}.{}").format(sql.Identifier(self._ohlcv.schema), sql.Identifier(self._ohlcv.table))
        row = self._conn.execute(
            sql.SQL("SELECT min({date})::date AS d FROM {table}").format(
                date=sql.Identifier(c["trade_date"]), table=table,
            )
        ).fetchone()
        if not row or not row["d"]: raise RuntimeError("OHLCV table has no trade date.")
        return str(row["d"])

    def _recent_trade_dates(self, count: int, as_of_date: str | None = None) -> list[str]:
        if count < 1:
            return []

        started = perf_counter()

        if as_of_date is None and len(self._trade_date_cache) >= count:
            self.last_metrics["date_lookup_seconds"] = perf_counter() - started
            self.last_metrics["date_cache_hit"] = True
            self.last_metrics["date_cache_size"] = len(self._trade_date_cache)
            return self._trade_date_cache[:count]

        c = self._ohlcv.columns
        table = sql.SQL("{}.{}").format(
            sql.Identifier(self._ohlcv.schema),
            sql.Identifier(self._ohlcv.table),
        )

        as_of = (
            sql.SQL("AND {d} <= %s::varchar").format(d=sql.Identifier(c["trade_date"]))
            if as_of_date else sql.SQL("")
        )
        q = sql.SQL("""
            SELECT DISTINCT {d} AS d
            FROM {t}
            WHERE {d} IS NOT NULL
              AND {d} <> ''
              {as_of}
            ORDER BY {d} DESC
            LIMIT %s
        """).format(
            d=sql.Identifier(c["trade_date"]),
            t=table,
            as_of=as_of,
        )

        params = (as_of_date, int(count)) if as_of_date else (int(count),)
        rows = self._conn.execute(q, params).fetchall()
        dates = [str(r["d"]).strip() for r in rows if r["d"] is not None]

        if as_of_date is None and len(dates) > len(self._trade_date_cache):
            self._trade_date_cache = dates

        self.last_metrics["date_lookup_seconds"] = perf_counter() - started
        self.last_metrics["date_cache_hit"] = False
        self.last_metrics["date_cache_size"] = len(self._trade_date_cache)
        self.last_metrics["date_lookup_method"] = "VARCHAR_INDEX_DISTINCT_DESC"
        return dates

    def period_trade_dates(self, start: str, end: str, *, weekly: bool = False) -> list[str]:
        """Return stored trade dates; weekly mode keeps each week's last stored date."""
        c = self._ohlcv.columns
        table = sql.SQL("{}.{}").format(sql.Identifier(self._ohlcv.schema), sql.Identifier(self._ohlcv.table))
        date = sql.Identifier(c["trade_date"])
        selected = (
            sql.SQL("max({d})::date").format(d=date)
            if weekly else sql.SQL("DISTINCT {d}::date").format(d=date)
        )
        grouped = sql.SQL("GROUP BY date_trunc('week',{d}::date)").format(d=date) if weekly else sql.SQL("")
        query = sql.SQL("SELECT {selected} AS d FROM {table} WHERE {date} BETWEEN %s::varchar AND %s::varchar {grouped} ORDER BY d").format(
            selected=selected, table=table, date=date, grouped=grouped,
        )
        return [str(row["d"]) for row in self._conn.execute(query, (start, end)).fetchall()]

    def period_dates_with_membership(self, universe: str, dates: list[str]) -> list[str]:
        """Exclude dates preceding the first stored index-membership snapshot."""
        required = {
            "KOSPI200": ("KOSPI200",),
            "KOSDAQ150": ("KOSDAQ150",),
            "KOSPI200+KOSDAQ150": ("KOSPI200", "KOSDAQ150"),
        }.get((universe or "").strip().upper())
        if not required or not dates:
            return dates

        available_from: list[str] = []
        for name in required:
            if not self._resolve_index_membership(name, dates[-1]):
                return []
            low, high = 0, len(dates) - 1
            while low < high:
                middle = (low + high) // 2
                if self._resolve_index_membership(name, dates[middle]):
                    high = middle
                else:
                    low = middle + 1
            available_from.append(dates[low])

        first_supported = max(available_from)
        return [value for value in dates if value >= first_supported]

    def _recent_week_dates(self, count: int, as_of: str) -> list[str]:
        """Return each recent ISO week's last stored trading date.

        The date column already has a descending lookup index.  Reading a small
        date window and grouping it in memory avoids repeatedly grouping the
        complete OHLCV table while a period screen evaluates many weeks.
        """
        result: list[str] = []
        seen: set[tuple[int, int]] = set()
        for value in self._recent_trade_dates(max(count * 7, count), as_of):
            parsed = calendar_date.fromisoformat(value)
            key = (parsed.isocalendar().year, parsed.isocalendar().week)
            if key in seen:
                continue
            seen.add(key); result.append(value)
            if len(result) == count:
                break
        return result

    def period_stock_metrics(self, codes: list[str], start: str, end: str) -> dict[tuple[str, str], dict]:
        """Load daily/calendar-week changes and DB values for occurrences in one query."""
        if not codes:
            return {}
        o, m, ot, mt, _, _ = self._common_parts()
        history_dates = self._recent_trade_dates(15, start)
        history_start = history_dates[-1] if history_dates else start
        value = (
            sql.SQL("o.{x}::double precision").format(x=sql.Identifier(o["trading_value"]))
            if "trading_value" in o else
            sql.SQL("o.{close}::double precision*COALESCE(o.{volume}::double precision,0)").format(
                close=sql.Identifier(o["close"]), volume=sql.Identifier(o["volume"]),
            )
        )
        industry = (
            sql.SQL("COALESCE(m.{x}::text,'')").format(x=sql.Identifier(m["industry"]))
            if "industry" in m else sql.SQL("''::text")
        )
        query = sql.SQL("""
            WITH history AS (
              SELECT o.{code}::text AS stock_code, o.{date}::date AS trade_date,
                     o.{close}::double precision AS close, {value} AS trading_value,
                     lag(o.{close}::double precision) OVER(PARTITION BY o.{code} ORDER BY o.{date}) AS previous_close
              FROM {ot} o
              WHERE o.{date} BETWEEN %s::varchar AND %s::varchar
                AND o.{code}::text=ANY(%s::text[])
            ), week_closes AS (
              SELECT stock_code, date_trunc('week',trade_date) AS week_start,
                     (array_agg(close ORDER BY trade_date DESC))[1] AS week_close
              FROM history GROUP BY stock_code,date_trunc('week',trade_date)
            ), weeks AS (
              SELECT *,lag(week_close) OVER(PARTITION BY stock_code ORDER BY week_start) AS previous_week_close
              FROM week_closes
            )
            SELECT h.*, m.{name}::text AS stock_name, {industry} AS industry,
                   CASE WHEN h.previous_close>0 THEN (h.close/h.previous_close-1)*100 END AS daily_pct,
                   CASE WHEN w.previous_week_close>0 THEN (h.close/w.previous_week_close-1)*100 END AS weekly_pct
            FROM history h JOIN {mt} m ON m.{mcode}::text=h.stock_code
            LEFT JOIN weeks w ON w.stock_code=h.stock_code AND w.week_start=date_trunc('week',h.trade_date)
            WHERE h.trade_date BETWEEN %s::date AND %s::date
        """).format(
            code=sql.Identifier(o["stock_code"]), date=sql.Identifier(o["trade_date"]),
            close=sql.Identifier(o["close"]), value=value, ot=ot, mt=mt,
            name=sql.Identifier(m["stock_name"]), mcode=sql.Identifier(m["stock_code"]), industry=industry,
        )
        rows = self._conn.execute(query, (history_start, end, codes, start, end)).fetchall()
        return {(str(row["stock_code"]).strip().zfill(6), str(row["trade_date"])): dict(row) for row in rows}


    def ensure_performance_indexes(self) -> list[dict[str, str]]:
        """Try to create recommended indexes, but never fail the application."""
        c = self._ohlcv.columns
        schema = self._ohlcv.schema
        table = self._ohlcv.table
        code = c["stock_code"]
        date = c["trade_date"]

        specs = [
            (
                f"idx_{table}_trade_date_stock_code",
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({}, {})").format(
                    sql.Identifier(f"idx_{table}_trade_date_stock_code"),
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    sql.Identifier(date),
                    sql.Identifier(code),
                ),
            ),
            (
                f"idx_{table}_stock_code_trade_date",
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({}, {} DESC)").format(
                    sql.Identifier(f"idx_{table}_stock_code_trade_date"),
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    sql.Identifier(code),
                    sql.Identifier(date),
                ),
            ),
        ]

        results: list[dict[str, str]] = []
        for name, stmt in specs:
            try:
                self._conn.execute(stmt)
                results.append({
                    "index": name,
                    "status": "CREATED_OR_PRESENT",
                    "detail": "",
                })
            except psycopg.errors.InsufficientPrivilege as exc:
                results.append({
                    "index": name,
                    "status": "INSUFFICIENT_PRIVILEGE",
                    "detail": str(exc).replace("\n", " ").strip(),
                })
            except Exception as exc:
                results.append({
                    "index": name,
                    "status": "ERROR",
                    "detail": f"{type(exc).__name__}: {exc}".replace("\n", " ").strip(),
                })

        return results

    def run(self, query: ScreeningQuery) -> list[ScreeningResult]:
        if not 1 <= query.limit <= 500:
            raise ValueError("screening limit must be 1..500")

        self.last_metrics = {}
        started = perf_counter()
        if query.kind == ScreeningKind.EMA_SIMILARITY:
            rows = self._ema_similarity(query)
        elif query.kind == ScreeningKind.HIGH_52W:
            rows = self._high_52w(query)
        elif query.kind == ScreeningKind.NEAR_HIGH_52W:
            rows = self._near_high_52w(query)
        elif query.kind == ScreeningKind.BOLLINGER_BREAKOUT:
            rows = self._bollinger_breakout(query)
        elif query.kind == ScreeningKind.DAILY_GAINERS:
            rows = self._daily_gainers(query)
        elif query.kind == ScreeningKind.WEEKLY_GAINERS:
            rows = self._weekly_gainers(query)
        elif query.kind == ScreeningKind.TURNOVER_TOP:
            rows = self._turnover_top(query)
        elif query.kind == ScreeningKind.WEEKLY_TURNOVER_TOP:
            rows = self._weekly_turnover_top(query)
        elif query.kind == ScreeningKind.EMA20_LEADING_SECTOR:
            rows = self._ema20_leading_sector(query)
        else:
            raise ValueError(f"Unsupported screening kind: {query.kind}")
        enrich_started = perf_counter()
        rows = self._enrich_display_fields(rows)
        self.last_metrics["display_enrichment_seconds"] = perf_counter() - enrich_started
        self.last_metrics["repository_total_seconds"] = perf_counter() - started
        self.last_metrics["result_count"] = len(rows)
        return rows

    def _enrich_display_fields(self, rows: list[ScreeningResult]) -> list[ScreeningResult]:
        """Fill every visible result column from one date-scoped PostgreSQL query."""
        if not rows: return rows
        o, m, ot, mt, market_expr, _ = self._common_parts()
        dates = self._recent_trade_dates(6, rows[0].trade_date)
        latest, previous, week_ago = dates[0], dates[min(1, len(dates)-1)], dates[-1]
        industry = (sql.SQL("COALESCE(NULLIF(m.{x}::text,''),'미분류')").format(x=sql.Identifier(m["industry"]))
                    if "industry" in m else sql.SQL("'미분류'::text"))
        market_cap = (sql.SQL("COALESCE(m.{x}::double precision,0)").format(x=sql.Identifier(m["market_cap"]))
                      if "market_cap" in m else sql.SQL("0::double precision"))
        amount = (sql.SQL("COALESCE(cur.{x}::double precision,0)").format(x=sql.Identifier(o["trading_value"]))
                  if "trading_value" in o else sql.SQL("cur.{c}::double precision*COALESCE(cur.{v}::double precision,0)").format(
                      c=sql.Identifier(o["close"]), v=sql.Identifier(o["volume"])))
        q = sql.SQL("""
          SELECT cur.{code}::text stock_code,{industry} industry,{market} market,
                 cur.{close}::double precision close,cur.{open}::double precision open,
                 cur.{high}::double precision high,cur.{low}::double precision low,
                 cur.{volume}::double precision volume,{amount} trading_value,{market_cap} market_cap,
                 CASE WHEN prev.{close}::double precision>0 THEN (cur.{close}::double precision/prev.{close}::double precision-1)*100 END daily_change,
                 CASE WHEN old.{close}::double precision>0 THEN (cur.{close}::double precision/old.{close}::double precision-1)*100 END weekly_change
          FROM {ot} cur JOIN {mt} m ON m.{mcode}=cur.{code}
          LEFT JOIN {ot} prev ON prev.{code}=cur.{code} AND prev.{date}=%s::varchar
          LEFT JOIN {ot} old ON old.{code}=cur.{code} AND old.{date}=%s::varchar
          WHERE cur.{date}=%s::varchar AND cur.{code}::text=ANY(%s::text[])
        """).format(code=sql.Identifier(o["stock_code"]), date=sql.Identifier(o["trade_date"]),
                      close=sql.Identifier(o["close"]), open=sql.Identifier(o["open"]),
                      high=sql.Identifier(o["high"]), low=sql.Identifier(o["low"]),
                      volume=sql.Identifier(o["volume"]), industry=industry, market=market_expr,
                      amount=amount, market_cap=market_cap, ot=ot, mt=mt,
                      mcode=sql.Identifier(m["stock_code"]))
        facts = {str(x["stock_code"]).strip(): x for x in self._conn.execute(
            q, (previous, week_ago, latest, [row.stock_code for row in rows])).fetchall()}
        enriched = []
        for row in rows:
            fact = facts.get(row.stock_code)
            if not fact: enriched.append(row); continue
            enriched.append(replace(row, industry=str(fact["industry"]), market=str(fact["market"] or row.market),
                                    close=float(fact["close"]), change_pct=float(fact["daily_change"] or 0),
                                    weekly_change_pct=float(fact["weekly_change"] or 0),
                                    trading_value=row.trading_value if row.trading_value is not None else float(fact["trading_value"]),
                                    open=float(fact["open"]), high=float(fact["high"]), low=float(fact["low"]),
                                    volume=float(fact["volume"]),
                                    market_cap=(row.market_cap if row.market_cap is not None
                                                else float(fact["market_cap"]))))
        return enriched

    def _common_parts(self):
        o = self._ohlcv.columns
        m = self._master.columns

        o_table = sql.SQL("{}.{}").format(
            sql.Identifier(self._ohlcv.schema), sql.Identifier(self._ohlcv.table)
        )
        m_table = sql.SQL("{}.{}").format(
            sql.Identifier(self._master.schema), sql.Identifier(self._master.table)
        )

        market_expr = (
            sql.SQL("COALESCE(m.{m}::text,'')").format(m=sql.Identifier(m["market"]))
            if "market" in m else sql.SQL("''::text")
        )

        if "is_spac" in m:
            spac_filter = sql.SQL("COALESCE(m.{x}, false)=false").format(
                x=sql.Identifier(m["is_spac"])
            )
        else:
            spac_filter = sql.SQL(
                "upper(COALESCE(m.{name}::text,'')) NOT LIKE '%%SPAC%%' "
                "AND COALESCE(m.{name}::text,'') NOT LIKE '%%스팩%%'"
            ).format(name=sql.Identifier(m["stock_name"]))

        return o, m, o_table, m_table, market_expr, spac_filter

    @staticmethod
    def _market_filter(market: str) -> tuple[str, str | None]:
        universe = (market or "ALL").strip().upper()
        if universe in {"ALL", "전체"}:
            return "ALL", None
        if universe in {"KOSPI", "KOSDAQ", "KONEX", "KOSPI+KOSDAQ", "KOSPI200", "KOSDAQ150", "KOSPI200+KOSDAQ150"}:
            return universe, universe
        raise ValueError(f"Unsupported screening universe: {market}")

    @staticmethod
    def _normalize_membership_label(value: object) -> str:
        text = str(value or "").upper()
        return "".join(ch for ch in text if ch.isalnum() or ("가" <= ch <= "힣"))

    def _membership_table_columns(self, schema: str, table: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (schema, table),
        ).fetchall()
        return [str(r["column_name"]) for r in rows]

    @staticmethod
    def _pick_membership_column(
        columns: list[str],
        candidates: tuple[str, ...],
    ) -> str | None:
        for name in candidates:
            if name in columns:
                return name
        return None

    def _resolve_index_membership(
        self,
        universe: str,
        as_of_date: str,
    ) -> dict[str, object] | None:
        cache = getattr(self, "_membership_resolution_cache", None)
        if cache is None:
            cache = {}
            self._membership_resolution_cache = cache

        cache_key = (universe, str(as_of_date))
        if cache_key in cache:
            return cache[cache_key]

        targets = {
            "KOSPI200": ("KOSPI200", "코스피200"),
            "KOSDAQ150": ("KOSDAQ150", "코스닥150"),
        }
        expected = {
            "KOSPI200": (190, 210),
            "KOSDAQ150": (140, 160),
        }
        wanted = targets[universe]
        low, high = expected[universe]

        candidates = (
            ("market_core", "index_membership_snapshot"),
            ("market_core", "ls_index_membership_raw"),
        )

        diagnostics: list[str] = []
        valid_matches: list[dict[str, object]] = []

        for schema, table in candidates:
            exists = self._conn.execute(
                "SELECT to_regclass(%s)::text AS rel",
                (f"{schema}.{table}",),
            ).fetchone()
            if not exists or not exists.get("rel"):
                diagnostics.append(f"{schema}.{table}:missing")
                continue

            columns = self._membership_table_columns(schema, table)
            code_col = self._pick_membership_column(
                columns,
                ("stock_code", "ticker", "code", "shcode"),
            )
            date_col = self._pick_membership_column(
                columns,
                ("observed_date", "as_of_date", "trade_date", "base_date", "date"),
            )
            key_col = self._pick_membership_column(
                columns,
                (
                    "index_key",
                    "index_code",
                    "index_name",
                    "sector_name",
                    "sector_code",
                    "group_name",
                    "universe",
                ),
            )

            if not (code_col and date_col and key_col):
                diagnostics.append(
                    f"{schema}.{table}:columns={','.join(columns)}"
                )
                continue

            tbl = sql.SQL("{}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table),
            )

            q = sql.SQL("""
                SELECT
                    {key}::text AS key_value,
                    max({date}::date) AS matched_date
                FROM {tbl}
                WHERE {date}::date <= %s::date
                GROUP BY {key}
            """).format(
                key=sql.Identifier(key_col),
                date=sql.Identifier(date_col),
                tbl=tbl,
            )
            keys = self._conn.execute(q, (as_of_date,)).fetchall()

            ranked: list[tuple[int, str, str]] = []
            for row in keys:
                key_value = str(row["key_value"])
                norm = self._normalize_membership_label(key_value)

                score = 0
                if universe in norm:
                    score = 100
                else:
                    for label in wanted:
                        if self._normalize_membership_label(label) in norm:
                            score = max(score, 90)

                if score <= 0:
                    continue

                ranked.append(
                    (score, key_value, str(row["matched_date"]))
                )

            ranked.sort(reverse=True)

            for _, key_value, matched_date in ranked:
                count_q = sql.SQL("""
                    SELECT count(DISTINCT {code})::int AS n
                    FROM {tbl}
                    WHERE {key}::text=%s
                      AND {date}::date=%s::date
                """).format(
                    code=sql.Identifier(code_col),
                    tbl=tbl,
                    key=sql.Identifier(key_col),
                    date=sql.Identifier(date_col),
                )
                count_row = self._conn.execute(
                    count_q,
                    (key_value, matched_date),
                ).fetchone()
                count = int(count_row["n"] or 0)

                diagnostics.append(
                    f"{schema}.{table}:{key_value}:{matched_date}:{count}"
                )

                if low <= count <= high:
                    valid_matches.append({
                        "schema": schema,
                        "table": table,
                        "code_col": code_col,
                        "date_col": date_col,
                        "key_col": key_col,
                        "key_value": key_value,
                        "matched_date": matched_date,
                        "count": count,
                    })

        if valid_matches:
            result = max(
                valid_matches,
                key=lambda item: (
                    str(item["matched_date"]),
                    item["table"] == "index_membership_snapshot",
                ),
            )
            cache[cache_key] = result
            self.last_metrics["membership_resolution"] = result
            self.last_metrics["membership_diagnostics"] = diagnostics
            return result

        # Second pass: accept a non-zero closest match if exact expected count is
        # not available, but only when label match was explicit.
        closest = None
        closest_delta = 10**9

        for schema, table in candidates:
            exists = self._conn.execute(
                "SELECT to_regclass(%s)::text AS rel",
                (f"{schema}.{table}",),
            ).fetchone()
            if not exists or not exists.get("rel"):
                continue

            columns = self._membership_table_columns(schema, table)
            code_col = self._pick_membership_column(
                columns, ("stock_code", "ticker", "code", "shcode")
            )
            date_col = self._pick_membership_column(
                columns, ("observed_date", "as_of_date", "trade_date", "base_date", "date")
            )
            key_col = self._pick_membership_column(
                columns,
                (
                    "index_key", "index_code", "index_name", "sector_name",
                    "sector_code", "group_name", "universe"
                ),
            )
            if not (code_col and date_col and key_col):
                continue

            tbl = sql.SQL("{}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
            rows = self._conn.execute(
                sql.SQL("""
                    SELECT {key}::text AS key_value,
                           max({date}::date) AS matched_date
                    FROM {tbl}
                    WHERE {date}::date <= %s::date
                    GROUP BY {key}
                """).format(
                    key=sql.Identifier(key_col),
                    date=sql.Identifier(date_col),
                    tbl=tbl,
                ),
                (as_of_date,),
            ).fetchall()

            for row in rows:
                key_value = str(row["key_value"])
                norm = self._normalize_membership_label(key_value)
                if not any(
                    self._normalize_membership_label(label) in norm
                    for label in wanted
                ):
                    continue

                matched_date = str(row["matched_date"])
                count_row = self._conn.execute(
                    sql.SQL("""
                        SELECT count(DISTINCT {code})::int AS n
                        FROM {tbl}
                        WHERE {key}::text=%s
                          AND {date}::date=%s::date
                    """).format(
                        code=sql.Identifier(code_col),
                        tbl=tbl,
                        key=sql.Identifier(key_col),
                        date=sql.Identifier(date_col),
                    ),
                    (key_value, matched_date),
                ).fetchone()
                count = int(count_row["n"] or 0)
                if count <= 0:
                    continue

                target = 200 if universe == "KOSPI200" else 150
                delta = abs(count - target)
                if delta < closest_delta:
                    closest_delta = delta
                    closest = {
                        "schema": schema,
                        "table": table,
                        "code_col": code_col,
                        "date_col": date_col,
                        "key_col": key_col,
                        "key_value": key_value,
                        "matched_date": matched_date,
                        "count": count,
                    }

        cache[cache_key] = closest
        self.last_metrics["membership_resolution"] = closest or {}
        self.last_metrics["membership_diagnostics"] = diagnostics
        return closest


    def _membership_source(self) -> str:
        cached = getattr(self, "_membership_source_cache", None)
        if cached is not None:
            return cached

        row = self._conn.execute(
            """
            SELECT
              to_regclass('market_core.index_membership_snapshot')::text AS snapshot,
              to_regclass('market_core.ls_index_membership_raw')::text AS raw
            """
        ).fetchone()

        available = []
        if row and row.get("snapshot"):
            available.append("snapshot")
        if row and row.get("raw"):
            available.append("raw")

        self._membership_source_cache = ",".join(available)
        return self._membership_source_cache


    def _universe_sql(
        self,
        m: dict[str, str],
        universe: str | None,
        *,
        stock_alias: str,
        stock_column: str,
        as_of_date: str,
    ):
        universe = (universe or "ALL").strip().upper()

        if universe in {"ALL", "전체"}:
            return sql.SQL(""), []

        if universe == "KOSPI+KOSDAQ":
            if "market" not in m:
                raise RuntimeError("종목 마스터에 시장 구분 열이 없습니다.")
            return sql.SQL("AND upper(COALESCE(m.{x}::text,'')) IN ('KOSPI','KOSDAQ')").format(
                x=sql.Identifier(m["market"])
            ), []

        if universe in {"KOSPI", "KOSDAQ", "KONEX"}:
            return self._market_sql(m, universe)

        if universe == "KOSPI200+KOSDAQ150":
            resolved = [self._resolve_index_membership(name, as_of_date) for name in ("KOSPI200", "KOSDAQ150")]
            if any(item is None for item in resolved):
                raise RuntimeError(f"통합 지수 구성종목을 PostgreSQL에서 찾지 못했습니다. 기준일={as_of_date}")
            clauses, params = [], []
            alias, stock = sql.Identifier(stock_alias), sql.Identifier(stock_column)
            for item in resolved:
                assert item is not None
                table = sql.SQL("{}.{}").format(sql.Identifier(item["schema"]), sql.Identifier(item["table"]))
                clauses.append(sql.SQL("""EXISTS (
                    SELECT 1 FROM {table} ims
                    WHERE ims.{key}::text=%s AND ims.{date}::date=%s::date
                      AND ims.{code}::text={alias}.{stock}::text
                )""").format(
                    table=table, key=sql.Identifier(item["key_col"]),
                    date=sql.Identifier(item["date_col"]), code=sql.Identifier(item["code_col"]),
                    alias=alias, stock=stock,
                ))
                params.extend((item["key_value"], item["matched_date"]))
            return sql.SQL("AND ({})").format(sql.SQL(" OR ").join(clauses)), params

        if universe not in {"KOSPI200", "KOSDAQ150"}:
            raise ValueError(f"Unsupported screening universe: {universe}")

        resolved = self._resolve_index_membership(universe, as_of_date)
        if not resolved:
            raise RuntimeError(
                f"{universe} 구성종목을 PostgreSQL에서 찾지 못했습니다. "
                f"기준일={as_of_date}. "
                "market_core.index_membership_snapshot / "
                "market_core.ls_index_membership_raw 값을 확인하십시오."
            )

        schema = resolved["schema"]
        table = resolved["table"]
        code_col = resolved["code_col"]
        date_col = resolved["date_col"]
        key_col = resolved["key_col"]
        key_value = resolved["key_value"]
        matched_date = resolved["matched_date"]

        alias = sql.Identifier(stock_alias)
        stock_code_ident = sql.Identifier(stock_column)
        tbl = sql.SQL("{}.{}").format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )

        fragment = sql.SQL("""
          AND EXISTS (
            SELECT 1
            FROM {tbl} ims
            WHERE ims.{key_col}::text = %s
              AND ims.{date_col}::date = %s::date
              AND ims.{code_col}::text = {alias}.{stock_code}::text
          )
        """).format(
            tbl=tbl,
            key_col=sql.Identifier(key_col),
            date_col=sql.Identifier(date_col),
            code_col=sql.Identifier(code_col),
            alias=alias,
            stock_code=stock_code_ident,
        )
        return fragment, [key_value, matched_date]


    def universe_status(self, as_of_date: str | None = None) -> dict[str, str | int]:
        as_of = as_of_date or self.latest_trade_date()
        result: dict[str, str | int] = {
            "membership_source": self._membership_source() or "missing",
            "as_of_date": as_of,
        }

        for universe in ("KOSPI200", "KOSDAQ150"):
            resolved = self._resolve_index_membership(universe, as_of)
            prefix = universe.lower()
            if resolved:
                result[f"{prefix}_count"] = int(resolved["count"])
                result[f"{prefix}_source"] = (
                    f"{resolved['schema']}.{resolved['table']}"
                )
                result[f"{prefix}_key"] = str(resolved["key_value"])
                result[f"{prefix}_date"] = str(resolved["matched_date"])
            else:
                result[f"{prefix}_count"] = 0
                result[f"{prefix}_source"] = "missing"
                result[f"{prefix}_key"] = ""
                result[f"{prefix}_date"] = ""
        return result


    def universe_count(self, universe: str, as_of_date: str | None = None) -> int:
        universe = universe.strip().upper()
        if universe not in {"KOSPI200", "KOSDAQ150"}:
            raise ValueError("universe_count supports KOSPI200/KOSDAQ150 only")

        as_of = as_of_date or self.latest_trade_date()
        resolved = self._resolve_index_membership(universe, as_of)
        return int(resolved["count"]) if resolved else 0


    def _market_sql(self, m: dict[str, str], market_value: str | None):
        if market_value and "market" in m:
            return (
                sql.SQL("AND upper(COALESCE(m.{x}::text,''))=%s").format(
                    x=sql.Identifier(m["market"])
                ),
                [market_value],
            )
        return sql.SQL(""), []

    def _rows_to_results(self, rows) -> list[ScreeningResult]:
        started = perf_counter()
        out: list[ScreeningResult] = []
        for position, r in enumerate(rows, 1):
            code = str(r["stock_code"]).strip()
            if code.isdigit():
                code = code.zfill(6)
            out.append(ScreeningResult(
                stock_code=code,
                stock_name=str(r["stock_name"] or "").strip(),
                market=str(r["market"] or "").strip(),
                trade_date=str(r["trade_date"]),
                close=float(r["close"]),
                change_pct=None if r.get("change_pct") is None else float(r["change_pct"]),
                trading_value=None if r.get("trading_value") is None else float(r["trading_value"]),
                high_52w=None if r.get("high_52w") is None else float(r["high_52w"]),
                distance_from_high_pct=(
                    None if r.get("distance_from_high_pct") is None
                    else float(r["distance_from_high_pct"])
                ),
                rank=int(r.get("rank") or position),
                industry=str(r.get("industry") or "").strip(),
                weekly_change_pct=None if r.get("weekly_change_pct") is None else float(r["weekly_change_pct"]),
                open=None if r.get("open") is None else float(r["open"]),
                high=None if r.get("high") is None else float(r["high"]),
                low=None if r.get("low") is None else float(r["low"]),
                volume=None if r.get("volume") is None else float(r["volume"]),
                market_cap=None if r.get("market_cap") is None else float(r["market_cap"]),
            ))
        self.last_metrics["python_transform_seconds"] = perf_counter() - started
        return out

    def _execute_timed(self, query, params):
        started = perf_counter()
        rows = self._conn.execute(query, params).fetchall()
        self.last_metrics["sql_seconds"] = perf_counter() - started
        return rows

    def _daily_gainers(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_trade_dates(2, query.as_of_date)
        if len(dates) < 2:
            return []
        latest_date, prev_date = dates[0], dates[1]

        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m,
            value,
            stock_alias="cur",
            stock_column=o["stock_code"],
            as_of_date=latest_date,
        )

        q = sql.SQL("""
        SELECT
            cur.{code}::text AS stock_code,
            m.{name}::text AS stock_name,
            {market} AS market,
            cur.{date}::date AS trade_date,
            cur.{close}::double precision AS close,
            CASE WHEN prev.{close} IS NULL OR prev.{close}=0 THEN NULL
                 ELSE (cur.{close}::double precision / prev.{close}::double precision - 1.0) * 100.0
            END AS change_pct,
            NULL::double precision AS trading_value,
            NULL::double precision AS high_52w,
            NULL::double precision AS distance_from_high_pct
        FROM {ot} cur
        JOIN {ot} prev
          ON prev.{code} = cur.{code}
         AND prev.{date} = %s::varchar
        JOIN {mt} m
          ON m.{mcode} = cur.{code}
        WHERE cur.{date} = %s::varchar
          AND {spac}
          {universe_where}
        ORDER BY change_pct DESC NULLS LAST
        LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]),
            name=sql.Identifier(m["stock_name"]),
            market=market_expr,
            date=sql.Identifier(o["trade_date"]),
            close=sql.Identifier(o["close"]),
            ot=ot,
            mt=mt,
            mcode=sql.Identifier(m["stock_code"]),
            spac=spac_filter,
            universe_where=universe_where,
        )

        params = [prev_date, latest_date] + universe_params + [int(query.limit)]
        self.last_metrics.update({
            "latest_date": latest_date,
            "comparison_date": prev_date,
            "universe": universe,
        })
        return self._rows_to_results(self._execute_timed(q, params))

    def _weekly_turnover_top(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_trade_dates(5, query.as_of_date)
        if len(dates) < 5:
            return []
        latest, start = dates[0], dates[-1]
        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m, value, stock_alias="cur", stock_column=o["stock_code"], as_of_date=latest
        )
        amount = (
            sql.SQL("COALESCE(o.{x}::double precision,0)").format(x=sql.Identifier(o["trading_value"]))
            if "trading_value" in o else
            sql.SQL("o.{close}::double precision * COALESCE(o.{vol}::double precision,0)").format(
                close=sql.Identifier(o["close"]), vol=sql.Identifier(o["volume"])
            )
        )
        q = sql.SQL("""
        WITH totals AS (
          SELECT o.{code} AS stock_code, sum({amount}) AS trading_value
          FROM {ot} o WHERE o.{date} BETWEEN %s::varchar AND %s::varchar
          GROUP BY o.{code}
        )
        SELECT cur.{code}::text AS stock_code, m.{name}::text AS stock_name,
          {market} AS market, cur.{date}::date AS trade_date,
          cur.{close}::double precision AS close, NULL::double precision AS change_pct,
          t.trading_value, NULL::double precision AS high_52w,
          NULL::double precision AS distance_from_high_pct
        FROM {ot} cur JOIN totals t ON t.stock_code=cur.{code}
        JOIN {mt} m ON m.{mcode}=cur.{code}
        WHERE cur.{date}=%s::varchar AND {spac} {universe_where}
        ORDER BY t.trading_value DESC NULLS LAST LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]), amount=amount, ot=ot,
            date=sql.Identifier(o["trade_date"]), name=sql.Identifier(m["stock_name"]),
            market=market_expr, close=sql.Identifier(o["close"]), mt=mt,
            mcode=sql.Identifier(m["stock_code"]), spac=spac_filter,
            universe_where=universe_where,
        )
        params = [start, latest, latest] + universe_params + [int(query.limit)]
        self.last_metrics.update({"latest_date": latest, "range_start_date": start, "universe": universe})
        return self._rows_to_results(self._execute_timed(q, params))

    def _near_high_52w(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_trade_dates(254, query.as_of_date)
        if not dates:
            return []
        latest, start = dates[0], dates[-1]
        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m, value, stock_alias="cur", stock_column=o["stock_code"], as_of_date=latest
        )
        q = sql.SQL("""
        WITH highs AS (
          SELECT {code} AS stock_code, max({high}::double precision) AS high_52w
          FROM {ot} WHERE {date} BETWEEN %s::varchar AND %s::varchar GROUP BY {code}
        ), candidates AS (
          SELECT cur.{code}::text AS stock_code, m.{name}::text AS stock_name,
            {market} AS market, cur.{date}::date AS trade_date,
            cur.{close}::double precision AS close, NULL::double precision AS change_pct,
            cur.{close}::double precision * cur.{volume}::double precision AS trading_value,
            h.high_52w, (cur.{close}::double precision/h.high_52w-1)*100 AS distance_from_high_pct
          FROM {ot} cur JOIN highs h ON h.stock_code=cur.{code}
          JOIN {mt} m ON m.{mcode}=cur.{code}
          WHERE cur.{date}=%s::varchar AND h.high_52w>0
            AND COALESCE(cur.{volume}::double precision,0)>0 AND {spac} {universe_where}
        ) SELECT * FROM candidates
          WHERE distance_from_high_pct BETWEEN %s AND %s
          ORDER BY distance_from_high_pct DESC, trading_value DESC LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]), high=sql.Identifier(o["high"]), ot=ot,
            date=sql.Identifier(o["trade_date"]), name=sql.Identifier(m["stock_name"]),
            market=market_expr, close=sql.Identifier(o["close"]), volume=sql.Identifier(o["volume"]),
            mt=mt, mcode=sql.Identifier(m["stock_code"]), spac=spac_filter,
            universe_where=universe_where,
        )
        params = [start, latest, latest] + universe_params + [float(query.near_low), float(query.near_high), int(query.limit)]
        return self._rows_to_results(self._execute_timed(q, params))

    def _bollinger_breakout(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_trade_dates(140, query.as_of_date)
        if len(dates) < 100:
            return []
        latest, start = dates[0], dates[-1]
        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m, value, stock_alias="cur", stock_column=o["stock_code"], as_of_date=latest
        )
        q = sql.SQL("""
        WITH weekly AS (
          SELECT DISTINCT ON ({code}, date_trunc('week',{date}::date))
            {code} AS stock_code, {date}::date AS trade_date, {close}::double precision AS close
          FROM {ot} WHERE {date} BETWEEN %s::varchar AND %s::varchar
          ORDER BY {code}, date_trunc('week',{date}::date), {date}::date DESC
        ), ranked AS (
          SELECT *, row_number() OVER(PARTITION BY stock_code ORDER BY trade_date DESC) rn FROM weekly
        ), bands AS (
          SELECT stock_code, max(close) FILTER(WHERE rn=1) AS close,
            avg(close) FILTER(WHERE rn BETWEEN 2 AND 21) AS mid,
            stddev_samp(close) FILTER(WHERE rn BETWEEN 2 AND 21) AS sd
          FROM ranked GROUP BY stock_code HAVING count(*)>=21
        )
        SELECT cur.{code}::text AS stock_code, m.{name}::text AS stock_name,
          {market} AS market, cur.{date}::date AS trade_date, cur.{close}::double precision AS close,
          (b.close/(b.mid+2*b.sd)-1)*100 AS change_pct,
          cur.{close}::double precision*cur.{volume}::double precision AS trading_value,
          (b.mid+2*b.sd) AS high_52w, NULL::double precision AS distance_from_high_pct
        FROM bands b JOIN {ot} cur ON cur.{code}=b.stock_code AND cur.{date}=%s::varchar
        JOIN {mt} m ON m.{mcode}=cur.{code}
        WHERE b.sd IS NOT NULL AND b.close>=b.mid+2*b.sd AND {spac} {universe_where}
        ORDER BY change_pct DESC, trading_value DESC LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]), date=sql.Identifier(o["trade_date"]),
            close=sql.Identifier(o["close"]), volume=sql.Identifier(o["volume"]), ot=ot,
            name=sql.Identifier(m["stock_name"]), market=market_expr, mt=mt,
            mcode=sql.Identifier(m["stock_code"]), spac=spac_filter, universe_where=universe_where,
        )
        params = [start, latest, latest] + universe_params + [int(query.limit)]
        return self._rows_to_results(self._execute_timed(q, params))

    def _ema_similarity(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_trade_dates(120, query.as_of_date)
        if len(dates) < 60:
            return []
        latest, start = dates[0], dates[-1]
        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m, value, stock_alias="cur", stock_column=o["stock_code"], as_of_date=latest
        )
        q = sql.SQL("""
        WITH ranked AS (
          SELECT {code} AS stock_code, {close}::double precision AS close,
            row_number() OVER(PARTITION BY {code} ORDER BY {date}::date DESC) rn
          FROM {ot} WHERE {date} BETWEEN %s::varchar AND %s::varchar
        ), f AS (
          SELECT stock_code,
            avg(close) FILTER(WHERE rn<=5) AS m5, avg(close) FILTER(WHERE rn<=20) AS m20,
            avg(close) FILTER(WHERE rn<=60) AS m60, avg(close) FILTER(WHERE rn<=120) AS m120
          FROM ranked GROUP BY stock_code HAVING count(*)>=60
        ), base AS (SELECT * FROM f WHERE stock_code::text=%s)
        SELECT cur.{code}::text AS stock_code, m.{name}::text AS stock_name,
          {market} AS market, cur.{date}::date AS trade_date, cur.{close}::double precision AS close,
          sqrt(power(f.m5/f.m20-base.m5/base.m20,2)+power(f.m20/f.m60-base.m20/base.m60,2)+power(f.m60/f.m120-base.m60/base.m120,2))*100 AS change_pct,
          cur.{close}::double precision*cur.{volume}::double precision AS trading_value,
          NULL::double precision AS high_52w, NULL::double precision AS distance_from_high_pct
        FROM f CROSS JOIN base JOIN {ot} cur ON cur.{code}=f.stock_code AND cur.{date}=%s::varchar
        JOIN {mt} m ON m.{mcode}=cur.{code}
        WHERE f.stock_code::text<>%s AND {spac} {universe_where}
        ORDER BY change_pct ASC, trading_value DESC LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]), close=sql.Identifier(o["close"]),
            date=sql.Identifier(o["trade_date"]), volume=sql.Identifier(o["volume"]), ot=ot,
            name=sql.Identifier(m["stock_name"]), market=market_expr, mt=mt,
            mcode=sql.Identifier(m["stock_code"]), spac=spac_filter, universe_where=universe_where,
        )
        code = str(query.comparison_ticker).strip().zfill(6)
        params = [start, latest, code, latest, code] + universe_params + [int(query.limit)]
        return self._rows_to_results(self._execute_timed(q, params))


    def _weekly_gainers(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_week_dates(2, query.as_of_date or self.latest_trade_date())
        if len(dates) < 2:
            return []
        latest_date, week_ago = dates

        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m,
            value,
            stock_alias="cur",
            stock_column=o["stock_code"],
            as_of_date=latest_date,
        )

        q = sql.SQL("""
        SELECT
            cur.{code}::text AS stock_code,
            m.{name}::text AS stock_name,
            {market} AS market,
            cur.{date}::date AS trade_date,
            cur.{close}::double precision AS close,
            CASE WHEN old.{close} IS NULL OR old.{close}=0 THEN NULL
                 ELSE (cur.{close}::double precision / old.{close}::double precision - 1.0) * 100.0
            END AS change_pct,
            NULL::double precision AS trading_value,
            NULL::double precision AS high_52w,
            NULL::double precision AS distance_from_high_pct
        FROM {ot} cur
        JOIN {ot} old
          ON old.{code} = cur.{code}
         AND old.{date} = %s::varchar
        JOIN {mt} m
          ON m.{mcode} = cur.{code}
        WHERE cur.{date} = %s::varchar
          AND {spac}
          {universe_where}
        ORDER BY change_pct DESC NULLS LAST
        LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]),
            name=sql.Identifier(m["stock_name"]),
            market=market_expr,
            date=sql.Identifier(o["trade_date"]),
            close=sql.Identifier(o["close"]),
            ot=ot,
            mt=mt,
            mcode=sql.Identifier(m["stock_code"]),
            spac=spac_filter,
            universe_where=universe_where,
        )

        params = [week_ago, latest_date] + universe_params + [int(query.limit)]
        self.last_metrics.update({
            "latest_date": latest_date,
            "comparison_date": week_ago,
            "universe": universe,
        })
        return self._rows_to_results(self._execute_timed(q, params))


    def _turnover_top(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()

        date_started = perf_counter()
        latest_date = query.as_of_date or self.latest_trade_date()
        self.last_metrics["date_lookup_seconds"] = perf_counter() - date_started
        self.last_metrics["date_cache_hit"] = False
        self.last_metrics["date_lookup_method"] = "MAX(trade_date)"

        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m,
            value,
            stock_alias="o",
            stock_column=o["stock_code"],
            as_of_date=latest_date,
        )

        if "trading_value" in o:
            value_expr = sql.SQL("o.{x}::double precision").format(
                x=sql.Identifier(o["trading_value"])
            )
        else:
            value_expr = sql.SQL(
                "(o.{close}::double precision * COALESCE(o.{vol},0)::double precision)"
            ).format(
                close=sql.Identifier(o["close"]),
                vol=sql.Identifier(o["volume"]),
            )

        q = sql.SQL("""
        SELECT
            o.{code}::text AS stock_code,
            m.{name}::text AS stock_name,
            {market} AS market,
            o.{date}::date AS trade_date,
            o.{close}::double precision AS close,
            NULL::double precision AS change_pct,
            {value_expr} AS trading_value,
            NULL::double precision AS high_52w,
            NULL::double precision AS distance_from_high_pct
        FROM {ot} o
        JOIN {mt} m ON m.{mcode} = o.{code}
        WHERE o.{date} = %s::varchar
          AND {spac}
          {universe_where}
        ORDER BY trading_value DESC NULLS LAST
        LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]),
            name=sql.Identifier(m["stock_name"]),
            market=market_expr,
            date=sql.Identifier(o["trade_date"]),
            close=sql.Identifier(o["close"]),
            value_expr=value_expr,
            ot=ot,
            mt=mt,
            mcode=sql.Identifier(m["stock_code"]),
            spac=spac_filter,
            universe_where=universe_where,
        )

        params = [latest_date] + universe_params + [int(query.limit)]
        self.last_metrics.update({
            "latest_date": latest_date,
            "universe": universe,
        })
        return self._rows_to_results(self._execute_timed(q, params))


    def _ema20_leading_sector(self, query: ScreeningQuery) -> list[ScreeningResult]:
        """Select liquid leaders near EMA20 using stored trading-day windows.

        Market capitalization at the requested date is reconstructed from that
        day's close and the DB-listed share count.  The event/reference day is
        the most recent day in the ten-session window satisfying both the
        turnover and open-to-close gain thresholds.
        """
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        required_ohlcv = {"open", "low", "close", "trading_value"}
        missing = sorted(required_ohlcv.difference(o))
        if missing:
            raise RuntimeError(
                "20일선+주도섹터에 필요한 OHLCV 열이 없습니다: "
                + ", ".join(missing)
            )
        if "shares" not in m:
            raise RuntimeError(
                "날짜 기준 시가총액 계산에 필요한 상장주식수 열이 없습니다."
            )

        # 252 sessions make the adjust=False EMA seed error immaterial while
        # keeping the screen bounded.  The actual predicates use exactly the
        # latest five and ten stored trading sessions.
        dates = self._recent_trade_dates(252, query.as_of_date)
        if len(dates) < 20:
            return []
        latest = dates[0]
        history_start = dates[-1]
        ten_start = dates[min(9, len(dates) - 1)]
        five_start = dates[min(4, len(dates) - 1)]

        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m,
            value,
            stock_alias="cur",
            stock_column=o["stock_code"],
            as_of_date=latest,
        )

        q = sql.SQL("""
        WITH recent AS MATERIALIZED (
          SELECT o.{code}::text AS stock_code,
                 o.{date}::date AS trade_date,
                 o.{open}::double precision AS open,
                 o.{low}::double precision AS low,
                 o.{close}::double precision AS close,
                 COALESCE(o.{amount}::double precision,0) AS trading_value
          FROM {ot} o
          WHERE o.{date} BETWEEN %s::varchar AND %s::varchar
        ), candidates AS MATERIALIZED (
          SELECT cur.{code}::text AS stock_code,
                 m.{name}::text AS stock_name,
                 {market} AS market,
                 cur.{date}::date AS trade_date,
                 cur.{close}::double precision AS close,
                 COALESCE(cur.{amount}::double precision,0) AS trading_value,
                 cur.{close}::double precision
                   * COALESCE(m.{shares}::double precision,0) AS market_cap,
                 reference_event.trade_date AS event_date,
                 reference_event.trading_value AS event_trading_value
          FROM {ot} cur
          JOIN {mt} m ON m.{mcode}=cur.{code}
          JOIN LATERAL (
          SELECT event.trade_date, event.trading_value
          FROM recent event
          WHERE event.stock_code=cur.{code}::text
            AND event.trading_value >= %s
            AND event.open > 0
            AND (event.close/event.open-1.0)*100.0 >= %s
            AND event.low <= cur.{close}::double precision
          ORDER BY event.trade_date DESC
          LIMIT 1
          ) reference_event ON TRUE
          WHERE cur.{date}=%s::varchar
            AND cur.{close}::double precision
                * COALESCE(m.{shares}::double precision,0) >= %s
            AND {spac}
            {universe_where}
            AND EXISTS (
              SELECT 1 FROM recent liquid
              WHERE liquid.stock_code=cur.{code}::text
                AND liquid.trading_value >= %s
            )
        ), ordered AS (
          SELECT o.{code}::text AS stock_code,
                 o.{date}::date AS trade_date,
                 o.{close}::double precision AS close,
                 row_number() OVER (
                   PARTITION BY o.{code} ORDER BY o.{date}::date
                 ) AS rn
          FROM {ot} o
          WHERE o.{date} BETWEEN %s::varchar AND %s::varchar
            AND o.{close}::double precision > 0
            AND o.{code}::text IN (SELECT stock_code FROM candidates)
        ), ema AS (
          SELECT ordered.*,
                 power(19.0/21.0, rn-1)
                   * first_value(close) OVER stock_history
                 + (2.0/21.0)*power(19.0/21.0, rn)
                   * sum(
                       CASE WHEN rn>1
                            THEN close/power(19.0/21.0, rn)
                            ELSE 0 END
                     ) OVER stock_history AS ema20
          FROM ordered
          WINDOW stock_history AS (
            PARTITION BY stock_code ORDER BY rn
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        )
        SELECT candidate.stock_code,
               candidate.stock_name,
               candidate.market,
               candidate.trade_date,
               candidate.close,
               NULL::double precision AS change_pct,
               candidate.trading_value,
               NULL::double precision AS high_52w,
               NULL::double precision AS distance_from_high_pct,
               candidate.market_cap
        FROM candidates candidate
        WHERE EXISTS (
            SELECT 1 FROM ema near_ema
            WHERE near_ema.stock_code=candidate.stock_code
              AND near_ema.rn >= 20
              AND near_ema.trade_date BETWEEN %s::date AND %s::date
              AND near_ema.close/NULLIF(near_ema.ema20,0) BETWEEN %s AND %s
        )
        ORDER BY candidate.event_date DESC,
                 candidate.event_trading_value DESC,
                 candidate.stock_code
        LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]),
            date=sql.Identifier(o["trade_date"]),
            open=sql.Identifier(o["open"]),
            low=sql.Identifier(o["low"]),
            close=sql.Identifier(o["close"]),
            amount=sql.Identifier(o["trading_value"]),
            ot=ot,
            mt=mt,
            name=sql.Identifier(m["stock_name"]),
            mcode=sql.Identifier(m["stock_code"]),
            shares=sql.Identifier(m["shares"]),
            market=market_expr,
            spac=spac_filter,
            universe_where=universe_where,
        )
        params = [
            ten_start,
            latest,
            100_000_000_000,
            10.0,
            latest,
            300_000_000_000,
        ] + universe_params + [
            100_000_000_000,
            history_start,
            latest,
            five_start,
            latest,
            0.9,
            1.2,
            int(query.limit),
        ]
        self.last_metrics.update({
            "latest_date": latest,
            "ten_session_start": ten_start,
            "five_session_start": five_start,
            "ema_history_start": history_start,
            "universe": universe,
            "market_cap_threshold": 300_000_000_000,
            "trading_value_threshold": 100_000_000_000,
        })
        return self._rows_to_results(self._execute_timed(q, params))


    def _high_52w(self, query: ScreeningQuery) -> list[ScreeningResult]:
        o, m, ot, mt, market_expr, spac_filter = self._common_parts()
        dates = self._recent_trade_dates(252, query.as_of_date)
        if not dates:
            return []
        latest_date = dates[0]
        start_date = dates[-1]

        universe, value = self._market_filter(query.market)
        universe_where, universe_params = self._universe_sql(
            m,
            value,
            stock_alias="cur",
            stock_column=o["stock_code"],
            as_of_date=latest_date,
        )

        value_expr = (
            sql.SQL("cur.{x}::double precision").format(
                x=sql.Identifier(o["trading_value"])
            )
            if "trading_value" in o
            else sql.SQL(
                "cur.{close}::double precision * cur.{volume}::double precision"
            ).format(
                close=sql.Identifier(o["close"]),
                volume=sql.Identifier(o["volume"]),
            )
        )

        industry_expr = (
            sql.SQL("COALESCE(m.{x}::text,'')").format(x=sql.Identifier(m["industry"]))
            if "industry" in m else sql.SQL("''::text")
        )
        market_cap_expr = (
            sql.SQL("m.{x}::double precision").format(x=sql.Identifier(m["market_cap"]))
            if "market_cap" in m else sql.SQL("NULL::double precision")
        )
        change_expr = (
            sql.SQL("cur.{x}::double precision").format(x=sql.Identifier(o["change_rate"]))
            if "change_rate" in o else sql.SQL(
                "CASE WHEN cur.previous_close>0 THEN (cur.{close}::double precision/cur.previous_close-1)*100 END"
            ).format(close=sql.Identifier(o["close"]))
        )
        event_factor_expr = (
            sql.SQL("""CASE WHEN raw_previous_close>0 AND 1+{rate}::double precision/100>0
              AND abs((({close}::double precision/(1+{rate}::double precision/100))/raw_previous_close)-1)>=0.02
              THEN ({close}::double precision/(1+{rate}::double precision/100))/raw_previous_close ELSE 1 END""").format(
                rate=sql.Identifier(o["change_rate"]), close=sql.Identifier(o["close"])
            ) if "change_rate" in o else sql.SQL("1::double precision")
        )

        q = sql.SQL("""
        WITH source AS (
          SELECT o.*,
                 lag(o.{close}::double precision) OVER (
                   PARTITION BY o.{code} ORDER BY o.{date}
                 ) AS raw_previous_close
          FROM {ot} o
          WHERE o.{date} BETWEEN %s::varchar AND %s::varchar
        ), events AS (
          SELECT source.*, {event_factor} AS event_factor FROM source
        ), raw AS (
          SELECT events.*,
                 exp(COALESCE(sum(ln(event_factor)) OVER (
                   PARTITION BY events.{code} ORDER BY events.{date}
                   ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
                 ),0)) AS adjustment
          FROM events
        ), daily0 AS (
          SELECT raw.*,
                 lag(raw.{close}::double precision) OVER (
                   PARTITION BY raw.{code} ORDER BY raw.{date}
                 ) AS previous_close
          FROM raw
        ), daily AS (
          SELECT daily0.*,
                 max(daily0.{high}::double precision) OVER (
                   PARTITION BY daily0.{code} ORDER BY daily0.{date}
                   ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING
                 ) AS prior_high_52w,
                 CASE WHEN previous_close>0 AND
                    (daily0.{close}::double precision/previous_close>1.35 OR
                     daily0.{close}::double precision/previous_close<0.65)
                 THEN 1 ELSE 0 END AS discontinuity
          FROM daily0
        ), checked AS (
          SELECT daily.*,
                 max(discontinuity) OVER (
                   PARTITION BY daily.{code} ORDER BY daily.{date}
                   ROWS BETWEEN 252 PRECEDING AND CURRENT ROW
                 ) AS uncertain_52w_basis
          FROM daily
        ), weekly AS (
          SELECT raw.{code} AS stock_code,
                 date_trunc('week', raw.{date}::date) AS week_start,
                 (array_agg(raw.{close}::double precision*raw.adjustment ORDER BY raw.{date} DESC))[1] AS weekly_close
          FROM raw
          GROUP BY raw.{code}, date_trunc('week', raw.{date}::date)
        ), weekly_change AS (
          SELECT weekly.*,
                 (weekly_close/lag(weekly_close) OVER (
                   PARTITION BY stock_code ORDER BY week_start
                 )-1)*100 AS weekly_change_pct,
                 row_number() OVER (PARTITION BY stock_code ORDER BY week_start DESC) AS recency
          FROM weekly
        )
        SELECT
            cur.{code}::text AS stock_code,
            m.{name}::text AS stock_name,
            {industry} AS industry,
            {market} AS market,
            cur.{date}::date AS trade_date,
            cur.{close}::double precision AS close,
            {change_rate} AS change_pct,
            wc.weekly_change_pct,
            {value_expr} AS trading_value,
            cur.{open}::double precision AS open,
            cur.{high}::double precision AS high,
            cur.{low}::double precision AS low,
            cur.{volume}::double precision AS volume,
            {market_cap} AS market_cap,
            cur.prior_high_52w AS high_52w,
            CASE WHEN cur.prior_high_52w IS NULL OR cur.prior_high_52w=0 THEN NULL
                 ELSE (cur.{close}::double precision / cur.prior_high_52w - 1.0) * 100.0
            END AS distance_from_high_pct
        FROM checked cur
        LEFT JOIN weekly_change wc ON wc.stock_code=cur.{code} AND wc.recency=1
        JOIN {mt} m
          ON m.{mcode} = cur.{code}
        WHERE cur.{date} = %s::varchar
          AND cur.prior_high_52w IS NOT NULL
          AND cur.{high}::double precision > cur.prior_high_52w
          AND cur.uncertain_52w_basis=0
          AND COALESCE(cur.{volume}::double precision, 0) > 0
          AND {spac}
          {universe_where}
        ORDER BY change_pct DESC NULLS LAST,
                 trading_value DESC NULLS LAST,
                 cur.{code}
        LIMIT %s
        """).format(
            code=sql.Identifier(o["stock_code"]),
            high=sql.Identifier(o["high"]),
            open=sql.Identifier(o["open"]),
            low=sql.Identifier(o["low"]),
            date=sql.Identifier(o["trade_date"]),
            close=sql.Identifier(o["close"]),
            volume=sql.Identifier(o["volume"]),
            value_expr=value_expr,
            name=sql.Identifier(m["stock_name"]),
            industry=industry_expr,
            market=market_expr,
            market_cap=market_cap_expr,
            change_rate=change_expr,
            event_factor=event_factor_expr,
            ot=ot,
            mt=mt,
            mcode=sql.Identifier(m["stock_code"]),
            spac=spac_filter,
            universe_where=universe_where,
        )

        params = [start_date, latest_date, latest_date] + universe_params + [int(query.limit)]
        self.last_metrics.update({
            "latest_date": latest_date,
            "range_start_date": start_date,
            "range_trade_days": len(dates),
            "universe": universe,
        })
        return self._rows_to_results(self._execute_timed(q, params))
