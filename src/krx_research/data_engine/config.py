from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from psycopg.conninfo import make_conninfo

from krx_research.environment import EnvironmentResolver
from krx_research.project import STOCK_ROOT


def _project_root() -> Path:
    return STOCK_ROOT


def load_environment() -> Path | None:
    """Load the canonical C:\\stock local environment into os.environ."""
    resolver = EnvironmentResolver(_project_root())
    values = resolver.values()
    for key, value in values.items():
        os.environ.setdefault(key, value)
    for path in reversed(resolver.sources()):
        if path.is_file():
            return path
    return None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def database_conninfo() -> str:
    """Return a psycopg-compatible PostgreSQL DSN and reject MariaDB settings."""
    load_environment()

    direct = _first_env(
        "KRX_DATABASE_URL",
        "DATABASE_URL",
        "POSTGRES_DATABASE_URL",
        "FINANCIAL_DATABASE_URL",
        "DB_URL",
    )
    if direct:
        for scheme in ("postgresql+psycopg://", "postgresql+psycopg2://"):
            if direct.startswith(scheme):
                direct = direct.replace(scheme, "postgresql://", 1)
        if direct.startswith(("mysql", "mariadb")):
            raise RuntimeError("MariaDB URL이 남아 있습니다. PostgreSQL URL로 변경하십시오.")
        if not direct.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("DATABASE_URL은 PostgreSQL URL이어야 합니다.")
        return direct

    host = _first_env("KRX_DB_HOST", "PGHOST", "DB_HOST") or "127.0.0.1"
    port = _first_env("KRX_DB_PORT", "PGPORT", "DB_PORT") or "5432"
    dbname = _first_env("KRX_DB_NAME", "PGDATABASE", "DB_NAME") or "krx_research"
    user = _first_env(
        "KRX_DB_USER", "KRX_DB_WRITE_USER", "PGUSER", "DB_USER"
    ) or "krx_writer"
    password = _first_env(
        "KRX_DB_PASSWORD", "KRX_DB_WRITE_PASSWORD", "PGPASSWORD", "DB_PASSWORD"
    )

    if port == "3306":
        raise RuntimeError(
            "DB 포트가 MariaDB 기본값 3306입니다. PostgreSQL 5432로 변경하십시오."
        )
    if not password:
        raise RuntimeError(
            "PostgreSQL 비밀번호가 없습니다. C:\\stock\\.env의 KRX_DB_WRITE_PASSWORD/KRX_DB_PASSWORD/PGPASSWORD를 확인하십시오."
        )

    return "\n".join(
        [
            f"host={host}",
            f"port={port}",
            f"dbname={dbname}",
            f"user={user}",
            f"password={password}",
        ]
    )


@dataclass(frozen=True, slots=True)
class DataEngineSettings:
    conninfo: str
    ohlcv_schema: str = "market"
    ohlcv_table: str = "ohlcv_daily"
    master_schema: str = "market"
    master_table: str = "security_master"
    core_schema: str = "market_core"
    cache_size: int = 128
    cache_ttl_seconds: int = 300
    provider_delay_seconds: float = 0.35

    @classmethod
    def from_environment(cls) -> "DataEngineSettings":
        load_environment()
        return cls(
            conninfo=database_conninfo(),
            ohlcv_schema=_first_env("KRX_OHLCV_SCHEMA") or "market",
            ohlcv_table=_first_env("KRX_OHLCV_TABLE") or "ohlcv_daily",
            master_schema=_first_env("KRX_MASTER_SCHEMA") or "market",
            master_table=_first_env("KRX_MASTER_TABLE") or "security_master",
            core_schema=_first_env("KRX_CORE_SCHEMA") or "market_core",
            cache_size=int(_first_env("KRX_QUERY_CACHE_SIZE") or "128"),
            cache_ttl_seconds=int(_first_env("KRX_QUERY_CACHE_TTL_SECONDS") or "300"),
            provider_delay_seconds=float(_first_env("KRX_PROVIDER_DELAY_SECONDS") or "0.35"),
        )

    def validate(self) -> None:
        """Validate cache limits and SQL identifiers before repository access."""
        if not 1 <= self.cache_size <= 4096:
            raise ValueError("cache_size는 1~4096 범위여야 합니다.")
        if not 0 <= self.cache_ttl_seconds <= 86_400:
            raise ValueError("cache_ttl_seconds는 0~86400 범위여야 합니다.")
        if not 0 <= self.provider_delay_seconds <= 10:
            raise ValueError("provider_delay_seconds는 0~10 범위여야 합니다.")
        for identifier in (
            self.ohlcv_schema,
            self.ohlcv_table,
            self.master_schema,
            self.master_table,
            self.core_schema,
        ):
            if not identifier.replace("_", "").isalnum():
                raise ValueError(f"허용되지 않은 SQL 식별자: {identifier!r}")


def settings_from_database_target(target: Any) -> DataEngineSettings:
    """Adapt the shared PostgreSQL target model for repository construction."""
    fields = {
        "host": target.host,
        "port": target.port,
        "dbname": target.database,
        "user": target.user,
        "password": target.password,
        "connect_timeout": target.connect_timeout,
        "sslmode": target.ssl_mode,
        "application_name": "krx_workstation_on_demand",
        "options": f"-c statement_timeout={target.statement_timeout * 1000}",
    }
    if target.ssl_root_cert is not None:
        fields["sslrootcert"] = str(target.ssl_root_cert)
    return DataEngineSettings(conninfo=make_conninfo(**fields))
