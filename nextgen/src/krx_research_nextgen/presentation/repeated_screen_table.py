from __future__ import annotations

import pandas as pd

from krx_research_nextgen.models.screening import RepeatedScreenResult
from krx_research_nextgen.presentation.number_format import format_number


HEADERS = (
    "등장 횟수", "종목코드", "종목명", "업종", "등장 기준일",
    "평균 일간(%)", "최고 일간(%)", "평균 주간(%)", "최고 주간(%)", "최근 거래대금(억원)",
)
ALIGNMENTS = ("right", "center", "left", "left", "center", "right", "right", "right", "right", "right")
FIELDS = (
    "appearance_count", "stock_code", "stock_name", "industry", "screen_dates",
    "average_daily_pct", "maximum_daily_pct", "average_weekly_pct",
    "maximum_weekly_pct", "latest_trading_value_eok",
)
LABELS = dict(zip(FIELDS, HEADERS, strict=True))


def result_frame(rows: list[RepeatedScreenResult]) -> pd.DataFrame:
    """Keep typed values so the common model sorts numbers as numbers."""
    return pd.DataFrame(
        [
            {
                "appearance_count": row.appearance_count,
                "stock_code": row.stock_code,
                "stock_name": row.stock_name,
                "industry": row.industry,
                "screen_dates": ", ".join(row.screen_dates),
                "average_daily_pct": row.average_daily_pct,
                "maximum_daily_pct": row.maximum_daily_pct,
                "average_weekly_pct": row.average_weekly_pct,
                "maximum_weekly_pct": row.maximum_weekly_pct,
                "latest_trading_value_eok": (
                    None if row.latest_trading_value is None
                    else row.latest_trading_value / 100_000_000
                ),
            }
            for row in rows
        ],
        columns=FIELDS,
    )


def row_values(row: RepeatedScreenResult) -> tuple[str, ...]:
    return (
        str(row.appearance_count), row.stock_code, row.stock_name, row.industry, ", ".join(row.screen_dates),
        format_number(row.average_daily_pct, 2), format_number(row.maximum_daily_pct, 2),
        format_number(row.average_weekly_pct, 2), format_number(row.maximum_weekly_pct, 2),
        format_number(None if row.latest_trading_value is None else row.latest_trading_value / 100_000_000, 1),
    )
