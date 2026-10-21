from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
import warnings

import pandas as pd

from .config import DataEngineSettings
from .postgresql import BaseDataRepository
from .service import MarketDataService


class ResearchStore(BaseDataRepository):
    """Compatibility facade for existing code that previously constructed ResearchStore(path)."""

    def __init__(
        self,
        path: str | Path | None = None,
        *args: Any,
        settings: DataEngineSettings | None = None,
        conninfo: str | None = None,
        read_only: bool = True,
        **kwargs: Any,
    ) -> None:
        # A legacy PostgreSQL/MariaDB path is intentionally ignored. PostgreSQL comes from .env.
        candidate_url = kwargs.pop("database_url", None) or kwargs.pop("url", None)
        path_text = str(path) if path is not None else ""
        self.path = Path(path) if path and "://" not in path_text else None
        if conninfo is None and path and path_text.startswith(
            ("postgresql://", "postgres://", "postgresql+psycopg://", "postgresql+psycopg2://")
        ):
            conninfo = str(path)
        if conninfo is None and candidate_url:
            conninfo = str(candidate_url)
        super().__init__(
            settings=settings,
            conninfo=conninfo,
            application_name="krx_research_compat_v30",
            read_only=read_only,
        )
        self.service = MarketDataService(
            self,
            cache_size=self.settings.cache_size,
            cache_ttl_seconds=self.settings.cache_ttl_seconds,
        )

    def get_technical_indicators(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        timeframe: str = "D",
        limit: int | None = None,
    ) -> pd.DataFrame:
        return self.service.get_indicators(ticker, timeframe, start, end, limit=limit)

    def latest_technical_indicator_date(self, as_of: date | str | None = None) -> date | None:
        latest = self.latest_ohlcv_date()
        if latest is None or as_of is None:
            return latest
        return min(latest, pd.Timestamp(as_of).date())

    def upsert_technical_indicators(self, frame: pd.DataFrame, *_: Any, **__: Any) -> int:
        warnings.warn(
            "v30에서는 기술지표를 DB에 저장하지 않습니다. 조회 시 자동 계산됩니다.",
            RuntimeWarning,
            stacklevel=2,
        )
        return 0

    def sync_technical_indicators(self, *_: Any, **__: Any) -> int:
        return 0

    def register_artifact(
        self,
        artifact_type: str,
        artifact_path: str | Path,
        reference_date: date | None = None,
        metadata: dict[str, Any] | None = None,
        **_: Any,
    ) -> int:
        try:
            from psycopg import sql as pg_sql
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - repository already checks this.
            raise RuntimeError("psycopg가 필요합니다.") from exc
        table = pg_sql.SQL("{}.artifacts").format(self._core_schema)
        with self.conn.transaction():
            row = self.conn.execute(
                pg_sql.SQL(
                    "INSERT INTO {} (artifact_type, artifact_path, reference_date, metadata) "
                    "VALUES (%s,%s,%s,%s) RETURNING artifact_id"
                ).format(table),
                [artifact_type, str(artifact_path), reference_date, Jsonb(metadata or {})],
            ).fetchone()
        return int(row["artifact_id"])

    def backup_to(self, *_: Any, **__: Any) -> None:
        raise RuntimeError(
            "PostgreSQL 백업은 파일 복사가 아니라 pg_dump로 수행해야 합니다. "
            "기존 프로젝트의 PostgreSQL 백업 메뉴를 사용하십시오."
        )


PostgresResearchStore = ResearchStore
