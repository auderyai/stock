from __future__ import annotations

from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from krx_research.data_engine import __version__
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.data_engine.service import MarketDataService


def main() -> int:
    settings = DataEngineSettings.from_environment()
    settings.validate()
    with BaseDataRepository(
        settings, application_name="krx_v30_verify", read_only=False
    ) as repository:
        repository.initialize_schema()
        database = repository.database_identity()
        if not database["ohlcv_exists"]:
            diagnostics = repository.relation_diagnostics()
            print(json.dumps({"database": database, "diagnostics": diagnostics}, ensure_ascii=False, indent=2, default=str))
            raise RuntimeError(
                f"기존 원천 일봉 테이블을 찾을 수 없습니다: {database['ohlcv_relation']}"
            )
        if not database["ohlcv_compatible"]:
            raise RuntimeError(
                f"원천 일봉 열 구성이 호환되지 않습니다: {database['ohlcv_relation']} "
                f"(layout={database['ohlcv_layout']})"
            )
        if not database["master_exists"]:
            raise RuntimeError(
                f"기존 종목 마스터를 찾을 수 없습니다: {database['master_relation']}"
            )
        sample_ticker = repository.sample_ohlcv_ticker()
        if sample_ticker is None:
            raise RuntimeError(f"원천 일봉 테이블이 비어 있습니다: {database['ohlcv_relation']}")
        sample_daily = repository.get_ohlcv(sample_ticker, limit=5)
        expected_columns = {"open_price", "high_price", "low_price", "close_price", "volume", "amount"}
        if sample_daily.empty or not expected_columns.issubset(sample_daily.columns):
            raise RuntimeError("v28 원천 일봉을 v30 표준 열로 변환하는 검증에 실패했습니다.")
        sample_weekly = MarketDataService(repository).get_bars(
            sample_ticker, "W", limit=2, indicators=True
        )
        if sample_weekly.empty or "rsi_14" not in sample_weekly.columns:
            raise RuntimeError("요청 시 주봉/보조지표 계산 검증에 실패했습니다.")
        checks = {
            "module_version": __version__,
            "database": database,
            "schema_version": repository.schema_version,
            "quick_check": repository.quick_check(),
            "ohlcv_coverage": repository.coverage("ohlcv"),
            "investor_coverage": repository.coverage("investor"),
            "sample_query": {
                "ticker": sample_ticker,
                "daily_rows": len(sample_daily),
                "weekly_rows": len(sample_weekly),
                "on_demand_indicator": "rsi_14",
            },
        }
        if checks["schema_version"] != "30":
            raise RuntimeError("market_core 스키마 버전이 30이 아닙니다.")
        print(json.dumps(checks, ensure_ascii=False, indent=2, default=str))
        print("검증 통과: PostgreSQL 원자료 + 온디맨드 연산 v30")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
