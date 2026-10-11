"""Backfill exact historical KOSPI 200/KOSDAQ 150 membership from KRX."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.index_membership import INDEX_GAINER_DEFINITIONS, IndexMembership
from krx_research.data_engine.config import DataEngineSettings, load_environment
from krx_research.data_engine.index_membership_store import PostgreSQLIndexMembershipStore
from krx_research.data_engine.postgresql import BaseDataRepository


SOURCE = "KRX:MDCSTAT00601_AUTH"
TICKER = re.compile(r"^[0-9A-Z]{6}$")


class KRXIndexMembershipBackfill:
    def __init__(self, settings: DataEngineSettings, stock_api, delay: float = 0.15) -> None:
        self.settings, self.stock_api, self.delay = settings, stock_api, delay
        self.store = PostgreSQLIndexMembershipStore(settings)

    def _trade_dates(self, start: dt.date, end: dt.date) -> list[dt.date]:
        with BaseDataRepository(self.settings, application_name="membership_backfill_dates") as repo:
            table = sql.SQL("{}.{}").format(
                sql.Identifier(self.settings.ohlcv_schema), sql.Identifier(self.settings.ohlcv_table),
            )
            rows = repo.conn.execute(
                sql.SQL("SELECT DISTINCT trade_date::date AS d FROM {} "
                        "WHERE trade_date::date BETWEEN %s::date AND %s::date ORDER BY d").format(table),
                (start, end),
            ).fetchall()
        return [row["d"] for row in rows]

    def _fetch(self, screen_type: str, day: dt.date) -> IndexMembership:
        definition = INDEX_GAINER_DEFINITIONS[screen_type]
        values = self.stock_api.get_index_portfolio_deposit_file(
            definition.known_pykrx_code, date=day.strftime("%Y%m%d"), alternative=False,
        )
        tickers = tuple(sorted({str(value).strip().upper().zfill(6) for value in values}))
        if any(not TICKER.fullmatch(value) for value in tickers):
            raise RuntimeError(f"{day} {definition.display_name} 구성종목 코드 형식 오류")
        if abs(len(tickers) - definition.expected_count) > 5:
            raise RuntimeError(
                f"{day} {definition.display_name} 구성종목 수 오류: "
                f"{len(tickers)} (명목 {definition.expected_count}, 허용 ±5)"
            )
        return IndexMembership(
            screen_type, definition.known_pykrx_code, definition.display_name,
            day, tickers, SOURCE,
        )

    def run(self, start: dt.date, end: dt.date) -> tuple[int, int]:
        dates = self._trade_dates(start, end)
        if not dates:
            raise RuntimeError("선택 기간에 PostgreSQL 거래일이 없습니다.")
        kinds = tuple(INDEX_GAINER_DEFINITIONS)
        previous: dict[str, tuple[str, ...]] = {}
        pending: list[IndexMembership] = []
        saved = 0
        for position, day in enumerate(dates, 1):
            for kind in kinds:
                membership = self._fetch(kind, day)
                if membership.tickers != previous.get(kind):
                    pending.append(membership); previous[kind] = membership.tickers
                if self.delay:
                    time.sleep(self.delay)
            if position % 20 == 0 or position == len(dates):
                saved += self.store.upsert_many(pending); pending.clear()
                print(f"[{position}/{len(dates)}] {day} · PostgreSQL {saved:,}행 저장", flush=True)
        return len(dates), saved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KRX 공식 과거 지수 구성종목 PostgreSQL 백필")
    parser.add_argument("--start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error("시작일은 종료일보다 늦을 수 없습니다.")
    load_environment()
    try:
        from pykrx import stock
    except Exception as error:  # KRX may temporarily return its IP-block page.
        print(f"KRX 로그인/접속 실패: {type(error).__name__}: {error}")
        print("이미 저장된 스냅샷은 보존됩니다. KRX 차단 해제 후 같은 기간으로 재실행하십시오.")
        return 2
    dates, rows = KRXIndexMembershipBackfill(
        DataEngineSettings.from_environment(), stock, max(0.0, args.delay),
    ).run(args.start, args.end)
    print(f"완료: 거래일 {dates:,}일 검증, 변경 스냅샷 {rows:,}행 저장")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
