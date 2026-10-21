"""Import a user-supplied NXT daily-history CSV/Excel file into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path

from krx_research.collectors.nxt_history import read_nxt_history_file, summarize_nxt_history
from krx_research.data_engine.config import DataEngineSettings, load_environment
from krx_research.data_engine.operational_repository import OperationalDataRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="NXT 종목별 일봉 CSV/Excel 파일")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment()
    frame = read_nxt_history_file(args.file)
    summary = summarize_nxt_history(frame)
    with OperationalDataRepository(
        DataEngineSettings.from_environment(), "nxt_history_import", read_only=False
    ) as repository:
        repository.initialize_schema()
        written = repository.upsert_venue_ohlcv(
            frame,
            venue="NXT",
            source_document=args.file.name,
        )
        missing = repository.missing_venue_dates(
            "NXT", summary["start_date"], summary["end_date"]
        )
    print(
        "NXT DB 적재 완료: "
        f"{written:,}행, {summary['tickers']:,}종목, "
        f"{summary['start_date']}~{summary['end_date']}"
    )
    if missing:
        rendered = ", ".join(value.isoformat() for value in missing[:10])
        print(f"주의: KRX 영업일 중 NXT 파일에 없는 날짜: {rendered}")
        return 2
    print("NXT 거래일 연속성 검사: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
