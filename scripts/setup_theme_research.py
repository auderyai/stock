"""Create the PostgreSQL theme_research schema and read permissions."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from krx_research.data_engine.config import load_environment
from krx_research.theme_research import ThemeResearchRepository, ThemeSpreadsheetImporter


ROLE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--import-file", action="append", default=[], type=Path,
        help="Schema creation 후 등록할 XLSX. 여러 번 지정할 수 있습니다.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment()
    reader = os.getenv("KRX_DB_READ_USER", "").strip() or None
    if reader and not ROLE_NAME.fullmatch(reader):
        raise RuntimeError("KRX_DB_READ_USER에 허용되지 않은 문자가 있습니다.")
    with ThemeResearchRepository(read_only=False) as repository:
        repository.initialize_schema(reader_role=reader)
        importer = ThemeSpreadsheetImporter(repository)
        for file_path in args.import_file:
            result = importer.import_file(file_path)
            state = "skipped" if result.skipped else "imported"
            print(
                f"{state}: {result.file_name}, date={result.report_date}, "
                f"rows={result.row_count}, matched={result.matched_count}, "
                f"unmatched={result.unmatched_count}"
            )
        summary = repository.summary()
    print(
        "theme_research schema ready: "
        f"dates={summary.get('date_count', 0)}, rows={summary.get('row_count', 0)}, "
        f"trading_values={summary.get('value_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
