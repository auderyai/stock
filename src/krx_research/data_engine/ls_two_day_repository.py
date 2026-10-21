from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping

from .postgresql import BaseDataRepository


class LSTwoDayRepository:
    """Own all PostgreSQL operations for the resumable LS t1702 collector."""

    def __init__(self, settings, ddl: str) -> None:
        self._repo = BaseDataRepository(
            settings, application_name="ls_two_days", read_only=False
        )
        self._ddl = ddl

    def __enter__(self):
        self._repo.__enter__()
        with self._repo.conn.transaction():
            self._repo.conn.execute(self._ddl)
        return self

    def __exit__(self, *args):
        return self._repo.__exit__(*args)

    def acquire_lock(self) -> bool:
        return bool(self._repo.conn.execute(
            "SELECT pg_try_advisory_lock(76340928029) AS acquired"
        ).fetchone()["acquired"])

    def prices(self, start: dt.date, end: dt.date):
        return self._repo.get_market_ohlcv(start, end)

    def security_master(self):
        return self._repo.get_security_master_frame()

    def completed(self, days: tuple[dt.date, ...]) -> dict[str, set[dt.date]]:
        rows = self._repo.conn.execute(
            """SELECT stock_code,trade_date FROM market_core.ls_investor_t1702_raw
            WHERE exchange_code='K' AND trade_date = ANY(%s)
            GROUP BY stock_code,trade_date
            HAVING count(DISTINCT (metric_code,side_code))=4""",
            (list(days),),
        ).fetchall()
        done: dict[str, set[dt.date]] = {}
        for row in rows:
            done.setdefault(row["stock_code"], set()).add(row["trade_date"])
        with self._repo.conn.transaction():
            for code, completed_days in done.items():
                for day in completed_days:
                    self._repo.conn.execute(
                        """INSERT INTO market_core.ls_investor_t1702_checkpoint
                        (stock_code,trade_date,exchange_code) VALUES (%s,%s,'K')
                        ON CONFLICT DO NOTHING""",
                        (code, day),
                    )
        return done

    def existing_keys(self, code: str, days: tuple[dt.date, ...]) -> set[tuple]:
        rows = self._repo.conn.execute(
            """SELECT trade_date,metric_code,side_code
            FROM market_core.ls_investor_t1702_raw
            WHERE stock_code=%s AND exchange_code='K' AND trade_date = ANY(%s)""",
            (code, list(days)),
        ).fetchall()
        return {(row["trade_date"], row["metric_code"], row["side_code"]) for row in rows}

    def save(self, code: str, found: Mapping[tuple, Mapping], complete: Iterable[dt.date]) -> None:
        with self._repo.conn.transaction():
            for (day, metric, side), fields in found.items():
                self._repo.conn.execute(
                    """INSERT INTO market_core.ls_investor_t1702_raw
                    (stock_code,trade_date,metric_code,side_code,exchange_code,source_fields)
                    VALUES (%s,%s,%s,%s,'K',%s::jsonb)
                    ON CONFLICT(stock_code,trade_date,metric_code,side_code,exchange_code)
                    DO UPDATE SET source_fields=EXCLUDED.source_fields,collected_at=now()""",
                    (code, day, metric, side, json.dumps(fields, ensure_ascii=False)),
                )
            for day in complete:
                self._repo.conn.execute(
                    """INSERT INTO market_core.ls_investor_t1702_checkpoint
                    (stock_code,trade_date,exchange_code) VALUES (%s,%s,'K')
                    ON CONFLICT DO NOTHING""",
                    (code, day),
                )
