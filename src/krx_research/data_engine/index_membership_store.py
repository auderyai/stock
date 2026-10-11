from __future__ import annotations

from collections.abc import Iterable
import datetime as dt
import json
from pathlib import Path

from krx_research.collectors.index_membership import INDEX_GAINER_DEFINITIONS, IndexMembership
from .postgresql import BaseDataRepository

DDL = (
    "CREATE TABLE IF NOT EXISTS market_core.index_membership_snapshot ("
    "index_key text NOT NULL, index_code text NOT NULL, index_name text NOT NULL, market text NOT NULL, "
    "observed_date date NOT NULL, stock_code varchar(12) NOT NULL, source text NOT NULL, "
    "collected_at timestamptz NOT NULL DEFAULT now(), "
    "PRIMARY KEY(index_key,observed_date,stock_code)); "
    "CREATE INDEX IF NOT EXISTS ix_index_membership_snapshot_lookup "
    "ON market_core.index_membership_snapshot(index_key,observed_date DESC);"
)


class PostgreSQLIndexMembershipStore:
    def __init__(self, settings) -> None:
        self.settings = settings

    def initialize(self) -> None:
        with BaseDataRepository(self.settings, application_name="index_membership_schema") as repo:
            with repo.conn.transaction():
                repo.conn.execute(DDL)

    def upsert(self, membership: IndexMembership) -> int:
        return self.upsert_many((membership,))

    def upsert_many(self, memberships: Iterable[IndexMembership]) -> int:
        """Atomically store one or more validated point-in-time snapshots."""
        memberships = tuple(memberships)
        if not memberships:
            return 0
        self.initialize()
        total = 0
        with BaseDataRepository(self.settings, application_name="index_membership_write") as repo:
            with repo.conn.transaction():
                for membership in memberships:
                    definition = INDEX_GAINER_DEFINITIONS[membership.screen_type]
                    rows = [
                        (membership.screen_type, membership.index_code, membership.index_name,
                         definition.market, membership.as_of_date, code, membership.source)
                        for code in membership.tickers
                    ]
                    repo.conn.execute(
                        "DELETE FROM market_core.index_membership_snapshot "
                        "WHERE index_key=%s AND observed_date=%s",
                        (membership.screen_type, membership.as_of_date),
                    )
                    with repo.conn.cursor() as cur:
                        cur.executemany(
                            "INSERT INTO market_core.index_membership_snapshot"
                            "(index_key,index_code,index_name,market,observed_date,stock_code,source) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s)", rows,
                        )
                    total += len(rows)
        return total

    def load(self, screen_type: str, as_of_date: dt.date) -> IndexMembership:
        definition = INDEX_GAINER_DEFINITIONS[screen_type]
        with BaseDataRepository(self.settings, application_name="index_membership_read") as repo:
            table = repo.conn.execute(
                "SELECT to_regclass('market_core.index_membership_snapshot') AS t"
            ).fetchone()["t"]
            if not table:
                raise RuntimeError(
                    "KOSPI200/KOSDAQ150 DB 구성종목이 없습니다. "
                    "메뉴 2번 '빠른 일봉 갱신'을 먼저 실행하십시오."
                )
            observed = repo.conn.execute(
                "SELECT max(observed_date) AS d "
                "FROM market_core.index_membership_snapshot "
                "WHERE index_key=%s AND observed_date<=%s",
                (screen_type, as_of_date),
            ).fetchone()["d"]
            if observed is None:
                raise RuntimeError(
                    f"{as_of_date} 이전 {definition.display_name} 구성종목 DB 스냅샷이 없습니다."
                )
            rows = repo.conn.execute(
                "SELECT index_code,index_name,stock_code,source "
                "FROM market_core.index_membership_snapshot "
                "WHERE index_key=%s AND observed_date=%s ORDER BY stock_code",
                (screen_type, observed),
            ).fetchall()

        tickers = tuple(str(row["stock_code"]) for row in rows)
        if abs(len(set(tickers)) - definition.expected_count) > 5:
            raise RuntimeError(
                f"{definition.display_name} DB 구성종목 수 오류: "
                f"{len(set(tickers))} (명목 {definition.expected_count}, 허용 ±5)"
            )
        first = rows[0]
        return IndexMembership(
            screen_type,
            str(first["index_code"]),
            str(first["index_name"]),
            observed,
            tickers,
            str(first["source"]),
        )

    def valid(self, screen_type: str, as_of_date: dt.date) -> bool:
        try:
            self.load(screen_type, as_of_date)
            return True
        except Exception:
            return False

    def import_legacy_cache(self, project_root: Path, as_of_date: dt.date) -> int:
        """One-way migration of the local C:\\stock cached membership into PostgreSQL."""
        candidates = (project_root / "config" / "index_membership_ls.json",)
        imported = 0
        for path in candidates:
            if not path.is_file():
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(document, dict):
                continue

            for screen_type, definition in INDEX_GAINER_DEFINITIONS.items():
                if self.valid(screen_type, as_of_date):
                    continue
                snapshots = document.get(screen_type)
                if not isinstance(snapshots, dict):
                    continue
                eligible = sorted(day for day in snapshots if day <= as_of_date.isoformat())
                if not eligible:
                    continue
                day = eligible[-1]
                saved = snapshots.get(day)
                if not isinstance(saved, dict):
                    continue
                tickers = tuple(
                    sorted(
                        {
                            str(code).strip().upper()
                            for code in saved.get("tickers", [])
                            if str(code).strip()
                        }
                    )
                )
                if abs(len(tickers) - definition.expected_count) > 5:
                    continue
                observed = dt.date.fromisoformat(str(saved.get("observed_date") or day))
                membership = IndexMembership(
                    screen_type,
                    str(saved.get("index_code") or definition.known_pykrx_code),
                    definition.display_name,
                    observed,
                    tickers,
                    f"MIGRATED:{path}",
                )
                self.upsert(membership)
                imported += 1
        return imported
