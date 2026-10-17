from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from krx_research.chart_learning import ChartLearningService, ChartPatternSample
from krx_research.database import resolve_database_target


def main() -> int:
    parser = argparse.ArgumentParser(description="Store one immutable local chart-learning sample.")
    parser.add_argument("--image", help="생략하면 Stock PostgreSQL 구간 자체를 학습 원본으로 사용")
    parser.add_argument("--ticker", default="", help="생략하면 Stock DB에서 정확한 종목명으로 식별")
    parser.add_argument("--name", default="", help="생략하면 Stock DB에서 종목코드로 확인")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--assessment", default="USER_SELECTED_DB_PATTERN_REFERENCE")
    parser.add_argument(
        "--rationale",
        default="사용자가 지정한 종목·기간을 DB 원자료 기반 패턴 기준 사례로 저장했습니다.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = ChartLearningService(resolve_database_target(root), root).store(ChartPatternSample(
        Path(args.image) if args.image else None, args.ticker, args.name,
        date.fromisoformat(args.start),
        date.fromisoformat(args.end), args.assessment, args.rationale,
    ))
    print(f"stored={result.sample_id} ticker={result.ticker} name={result.company_name} "
          f"db_date={result.db_reference_date} "
          f"duplicate={str(result.duplicate).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
