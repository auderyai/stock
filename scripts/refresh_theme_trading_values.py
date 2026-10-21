"""Reconnect stored hot-theme rows to exact-date PostgreSQL trading values."""

from __future__ import annotations

from krx_research.theme_research import ThemeResearchRepository


def main() -> int:
    with ThemeResearchRepository(read_only=False) as repository:
        repository.initialize_schema()
        dates = repository.available_dates()
        if not dates:
            print("theme_research: no active spreadsheet rows")
            return 0
        result = repository.refresh_trading_values(
            min(dates), max(dates), only_missing=False, include_public=True
        )
        summary = repository.summary()
    print(
        "theme_research trading-value refresh: "
        f"examined={result['examined']}, updated={result['updated']}, "
        f"market_updated={result['market_updated']}, "
        f"krx={result['krx_updated']}, naver_estimate={result['naver_updated']}, "
        f"missing={result['missing']}, market_missing={result['market_missing']}, "
        f"total_values={summary.get('value_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
