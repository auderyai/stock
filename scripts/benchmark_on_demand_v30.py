from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.operational_repository import OperationalDataRepository
from krx_research.data_engine.service import MarketDataService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="222800")
    parser.add_argument("--timeframe", choices=["D", "W", "M", "Q", "Y"], default="D")
    args = parser.parse_args()
    with OperationalDataRepository(DataEngineSettings.from_environment(), "benchmark_on_demand") as repository:
        service = MarketDataService(repository, cache_ttl_seconds=300)
        started = perf_counter()
        cold = service.get_indicators(args.ticker, args.timeframe)
        cold_seconds = perf_counter() - started
        started = perf_counter()
        warm = service.get_indicators(args.ticker, args.timeframe)
        warm_seconds = perf_counter() - started
    print(f"ticker={args.ticker} timeframe={args.timeframe} rows={len(cold):,}")
    print(f"DB 읽기 + 최초 계산: {cold_seconds:.4f}초")
    print(f"메모리 캐시 재조회: {warm_seconds:.4f}초")
    if len(cold) != len(warm):
        raise RuntimeError("캐시 결과 행 수가 다릅니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
