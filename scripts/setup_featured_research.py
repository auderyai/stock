"""Create featured_research schema and optionally import daily XLSX files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

from krx_research.data_engine.config import load_environment
from krx_research.featured_research import FeaturedResearchRepository, FeaturedSpreadsheetImporter

ROLE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-file", action="append", default=[], type=Path)
    args = parser.parse_args()
    load_environment()
    reader = os.getenv("KRX_DB_READ_USER", "").strip() or None
    if reader and not ROLE_NAME.fullmatch(reader):
        raise RuntimeError("KRX_DB_READ_USER에 허용되지 않은 문자가 있습니다.")
    with FeaturedResearchRepository(read_only=False) as repository:
        repository.initialize_schema(reader_role=reader)
        importer = FeaturedSpreadsheetImporter(repository)
        for path in args.import_file:
            result = importer.import_file(path)
            state = "skipped" if result.skipped else "imported"
            print(f"{state}: {result.file_name}, date={result.report_date}, rows={result.row_count}, matched={result.matched_count}, unmatched={result.unmatched_count}")
        summary = repository.summary()
    print(f"featured_research schema ready: dates={summary.get('date_count', 0)}, rows={summary.get('row_count', 0)}, trading_values={summary.get('value_count', 0)}, markets={summary.get('market_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
