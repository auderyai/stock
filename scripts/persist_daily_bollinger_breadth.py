from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nextgen" / "src"), str(ROOT / "src")]

from krx_research_nextgen.repositories.bollinger_breadth_repository import BollingerBreadthRepository
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.bollinger_breadth_service import BollingerBreadthService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="종가 기준 일별 볼린저 돌파 및 시장 집계 저장")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    with ScreeningRepository() as source:
        rows, universe = BollingerBreadthService(source, BollingerBreadthRepository()).refresh(args.as_of)
    upper = sum(row["direction"] == "UPPER" for row in rows)
    lower = sum(row["direction"] == "LOWER" for row in rows)
    print(f"[BOLLINGER BREADTH] {args.as_of} universe={universe} upper={upper} lower={lower}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
