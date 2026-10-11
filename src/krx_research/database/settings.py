"""PostgreSQL-only database configuration for new_stock."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from krx_research.environment import EnvironmentResolver


class DatabaseConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PostgreSQLSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_timeout: int = 10
    statement_timeout: int = 120
    ssl_mode: str = "prefer"
    ssl_root_cert: Path | None = None
    dump_executable: str = "pg_dump"

    @property
    def label(self) -> str:
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"


DatabaseTarget: TypeAlias = PostgreSQLSettings
_DB = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_USER = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _positive(values: dict[str, str], key: str, default: int) -> int:
    try:
        value = int(values.get(key, str(default)).strip())
    except ValueError as error:
        raise DatabaseConfigurationError(f"{key}는 정수여야 합니다.") from error
    if value < 1:
        raise DatabaseConfigurationError(f"{key}는 양수여야 합니다.")
    return value


def _first(values: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = values.get(key)
        if value and value.strip():
            return value.strip()
    return default


def _resolve(values: dict[str, str], read_only: bool) -> PostgreSQLSettings:
    engine = _first(values, "KRX_DB_ENGINE", default="postgresql").lower()
    if engine not in {"postgresql", "postgres", "pgsql"}:
        raise DatabaseConfigurationError(
            "Stock은 PostgreSQL 전용입니다. KRX_DB_ENGINE=postgresql 로 설정하십시오."
        )

    host = _first(values, "KRX_DB_HOST", "PGHOST", "DB_HOST", default="127.0.0.1")
    database = _first(values, "KRX_DB_NAME", "PGDATABASE", "DB_NAME", default="krx_research")

    if read_only:
        user = _first(
            values,
            "KRX_DB_READ_USER",
            "KRX_DB_USER",
            "KRX_DB_WRITE_USER",
            "PGUSER",
            "DB_USER",
            default="krx_writer",
        )
        password = _first(
            values,
            "KRX_DB_READ_PASSWORD",
            "KRX_DB_PASSWORD",
            "KRX_DB_WRITE_PASSWORD",
            "PGPASSWORD",
            "DB_PASSWORD",
        )
    else:
        user = _first(
            values,
            "KRX_DB_USER",
            "KRX_DB_WRITE_USER",
            "PGUSER",
            "DB_USER",
            default="krx_writer",
        )
        password = _first(
            values,
            "KRX_DB_PASSWORD",
            "KRX_DB_WRITE_PASSWORD",
            "PGPASSWORD",
            "DB_PASSWORD",
        )

    missing = [
        label
        for label, value in (
            ("KRX_DB_HOST", host),
            ("PostgreSQL 비밀번호", password),
        )
        if not value
    ]
    if missing:
        raise DatabaseConfigurationError("PostgreSQL 설정 누락: " + ", ".join(missing))

    if not _DB.fullmatch(database):
        raise DatabaseConfigurationError("KRX_DB_NAME 형식 오류")
    if not _USER.fullmatch(user):
        raise DatabaseConfigurationError("PostgreSQL 사용자명 형식 오류")

    port = _positive(values, "KRX_DB_PORT", 5432)
    if port == 3306:
        raise DatabaseConfigurationError(
            "MariaDB 포트 3306은 사용할 수 없습니다. PostgreSQL 포트를 지정하십시오."
        )
    if port > 65535:
        raise DatabaseConfigurationError("KRX_DB_PORT 범위 오류")

    ssl_mode = _first(values, "KRX_DB_SSL_MODE", default="prefer").lower()
    if ssl_mode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise DatabaseConfigurationError("KRX_DB_SSL_MODE 형식 오류")

    cert_text = _first(values, "KRX_DB_SSL_CA")
    cert = Path(cert_text).expanduser().resolve() if cert_text else None
    if cert and not cert.is_file():
        raise DatabaseConfigurationError(f"TLS CA 파일 없음: {cert}")

    return PostgreSQLSettings(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=_positive(values, "KRX_DB_CONNECT_TIMEOUT", 10),
        statement_timeout=_positive(
            values, "KRX_DB_STATEMENT_TIMEOUT", 60 if read_only else 120
        ),
        ssl_mode=ssl_mode,
        ssl_root_cert=cert,
        dump_executable=_first(values, "KRX_DB_DUMP", default="pg_dump"),
    )


def resolve_database_target(
    project_root: str | Path, *, read_only: bool = False, **_ignored
) -> PostgreSQLSettings:
    return _resolve(EnvironmentResolver(project_root).values(), read_only)


def resolve_database_target_from_env_file(
    env_file: str | Path, *, read_only: bool = False
) -> PostgreSQLSettings:
    path = Path(env_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    # Exact-file resolution intentionally does not merge process/shared environment.
    values = EnvironmentResolver._read(path)
    return _resolve(values, read_only)


def database_label(target: DatabaseTarget) -> str:
    return target.label
