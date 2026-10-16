"""로컬 PostgreSQL에서 주가·이동평균 유사 패턴을 검색한다."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.database import resolve_database_target
from krx_research.qt.services.pattern_similarity import (
    MovingAverageKind, MovingAverageSpec, PatternSearchQuery, PatternSimilaritySearchService,
    PatternVectorCache, PostgreSQLPatternRepository,
)

def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("security", help="종목코드 또는 정확한 종목명")
    result.add_argument("start", type=date.fromisoformat, help="시작일 YYYY-MM-DD")
    result.add_argument("end", type=date.fromisoformat, help="종료일 YYYY-MM-DD")
    result.add_argument("--average", choices=[item.value for item in MovingAverageKind], default="SMA")
    result.add_argument("--periods", type=int, nargs="+", default=[5, 20, 60])
    result.add_argument("--top", type=int, default=20)
    result.add_argument("--volume", action="store_true", help="거래량 모양도 비교")
    result.add_argument("--no-price", action="store_true", help="종가 모양 비교 제외")
    result.add_argument("--no-cache", action="store_true", help="로컬 벡터 캐시 미사용")
    result.add_argument("--json", action="store_true", help="JSON으로 출력")
    return result


def main() -> int:
    args = parser().parse_args()
    query = PatternSearchQuery(
        args.security, args.start, args.end,
        MovingAverageSpec(MovingAverageKind(args.average), tuple(args.periods)),
        args.top, not args.no_price, args.volume,
    )
    cache = None if args.no_cache else PatternVectorCache(ROOT / ".local_cache" / "pattern_vectors")
    service = PatternSimilaritySearchService(
        PostgreSQLPatternRepository(resolve_database_target(ROOT, read_only=True)), cache
    )
    rows = service.search(query)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, default=str, indent=2))
    else:
        print(f"기준: {args.security} | {query.averages.kind.value} {query.averages.periods} | "
              f"{query.start}~{query.end} | 결과 {len(rows)}건")
        for rank, row in enumerate(rows, 1):
            print(f"{rank:>2}. {row['stock_name']}({row['stock_code']}) "
                  f"유사도 {row['similarity_pct']:.2f}% | 최근 {row['db_recent_date']} "
                  f"등락 {row['rise_pct']}% | 종가 {row['close']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
