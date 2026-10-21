"""Prepare read-only PostgreSQL permissions for workstation v31."""

from __future__ import annotations

import os
import re

from krx_research.data_engine.config import DataEngineSettings, load_environment
from krx_research.database.administrative_repository import AdministrativeRepository


ROLE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def main() -> int:
    load_environment()
    reader = os.getenv("KRX_DB_READ_USER", "").strip()
    if not reader:
        raise RuntimeError(".env에 KRX_DB_READ_USER가 없습니다.")
    if not ROLE_NAME.fullmatch(reader):
        raise RuntimeError("KRX_DB_READ_USER에 허용되지 않은 문자가 있습니다.")
    with AdministrativeRepository(
        DataEngineSettings.from_environment(),
        application_name="setup_workstation",
        read_only=False,
    ) as repository:
        identity = repository.grant_reader(reader)
    print(
        "workstation v31 DB 준비 완료: "
        f"reader={reader}, ohlcv={identity['ohlcv_relation']}, "
        f"layout={identity['ohlcv_layout']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
