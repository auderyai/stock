"""Prepare read-only PostgreSQL permissions for workstation v31."""

from __future__ import annotations

import os
import re

from krx_research.data_engine.config import DataEngineSettings, load_environment
from krx_research.data_engine.postgresql import BaseDataRepository


ROLE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def main() -> int:
    load_environment()
    reader = os.getenv("KRX_DB_READ_USER", "").strip()
    if not reader:
        raise RuntimeError(".env에 KRX_DB_READ_USER가 없습니다.")
    if not ROLE_NAME.fullmatch(reader):
        raise RuntimeError("KRX_DB_READ_USER에 허용되지 않은 문자가 있습니다.")
    try:
        from psycopg import sql
    except ImportError as error:
        raise RuntimeError("psycopg가 설치되지 않았습니다.") from error

    with BaseDataRepository(DataEngineSettings.from_environment()) as repository:
        role = sql.Identifier(reader)
        with repository.conn.transaction():
            repository.conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA market, market_core TO {}").format(role)
            )
            repository.conn.execute(
                sql.SQL(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA market, market_core TO {}"
                ).format(role)
            )
            repository.conn.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA market_core "
                    "GRANT SELECT ON TABLES TO {}"
                ).format(role)
            )
        identity = repository.database_identity()
    print(
        "workstation v31 DB 준비 완료: "
        f"reader={reader}, ohlcv={identity['ohlcv_relation']}, "
        f"layout={identity['ohlcv_layout']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
