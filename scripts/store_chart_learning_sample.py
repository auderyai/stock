from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from krx_research.chart_learning import ChartLearningService, ChartPatternSample
from krx_research.database import resolve_database_target


def main() -> int:
    parser = argparse.ArgumentParser(description="Store one immutable local chart-learning sample.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--assessment", required=True)
    parser.add_argument("--rationale", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = ChartLearningService(resolve_database_target(root), root).store(ChartPatternSample(
        Path(args.image), args.ticker, args.name, date.fromisoformat(args.start),
        date.fromisoformat(args.end), args.assessment, args.rationale,
    ))
    print(f"stored={result.sample_id} ticker={result.ticker} db_date={result.db_reference_date} "
          f"duplicate={str(result.duplicate).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
