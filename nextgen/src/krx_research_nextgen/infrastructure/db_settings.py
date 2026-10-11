from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ENV_FILE = Path(r"C:\stock\.env")


def _read_env(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise RuntimeError(f"Environment file not found: {path}")
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _first(values: dict[str, str], names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = values.get(name, "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class PostgreSQLSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    preferred_ohlcv_schema: str = "market"
    preferred_ohlcv_table: str = "ohlcv_daily"
    preferred_master_schema: str = "market"
    preferred_master_table: str = "security_master"

    @classmethod
    def from_c_stock_env(cls) -> "PostgreSQLSettings":
        values = _read_env()
        host = _first(values, ("KRX_DB_HOST", "PGHOST", "DB_HOST"), "127.0.0.1")
        port = int(_first(values, ("KRX_DB_PORT", "PGPORT", "DB_PORT"), "5432"))
        dbname = _first(values, ("KRX_DB_NAME", "PGDATABASE", "DB_NAME"), "krx_research")
        user = _first(
            values,
            ("KRX_DB_READ_USER", "KRX_DB_USER", "KRX_DB_WRITE_USER", "PGUSER", "DB_USER"),
            "krx_writer",
        )
        password = _first(
            values,
            ("KRX_DB_READ_PASSWORD", "KRX_DB_PASSWORD", "KRX_DB_WRITE_PASSWORD", "PGPASSWORD", "DB_PASSWORD"),
        )
        if not password:
            raise RuntimeError("PostgreSQL password is missing in C:\\stock\\.env")
        if port == 3306:
            raise RuntimeError("MariaDB port 3306 is forbidden.")
        return cls(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            preferred_ohlcv_schema=_first(values, ("KRX_OHLCV_SCHEMA",), "market"),
            preferred_ohlcv_table=_first(values, ("KRX_OHLCV_TABLE",), "ohlcv_daily"),
            preferred_master_schema=_first(values, ("KRX_MASTER_SCHEMA",), "market"),
            preferred_master_table=_first(values, ("KRX_MASTER_TABLE",), "security_master"),
        )

    def connect_kwargs(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "connect_timeout": 10,
        }
