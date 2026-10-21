from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from krx_research_nextgen.models.screening import ScreeningResult
from krx_research_nextgen.presentation.number_format import format_number


HEADERS = (
    "기준일", "순위", "종목코드", "종목명", "업종", "종가", "일간(%)", "주간(%)",
    "거래대금(억원)", "시가", "고가", "저가", "거래량", "시장", "시가총액(억원)",
)

LABELS = dict(zip(
    (
        "trade_date", "rank", "stock_code", "stock_name", "industry", "close",
        "change_pct", "weekly_change_pct", "trading_value_eok", "open", "high",
        "low", "volume", "market", "market_cap_eok",
    ),
    HEADERS,
))


def result_frame(rows: list[ScreeningResult]) -> pd.DataFrame:
    records = []
    for item in rows:
        record = asdict(item)
        record["trading_value_eok"] = (
            None if item.trading_value is None else item.trading_value / 100_000_000
        )
        record["market_cap_eok"] = (
            None if item.market_cap is None else item.market_cap / 100_000_000
        )
        records.append(record)
    return pd.DataFrame(records, columns=tuple(LABELS))


def _number(value: float | None, decimals: int = 0) -> str:
    return format_number(value, decimals)


def row_values(item: ScreeningResult, *, include_date: bool = True) -> tuple[str, ...]:
    values = (
        item.trade_date, str(item.rank), item.stock_code, item.stock_name, item.industry,
        _number(item.close), _number(item.change_pct, 2), _number(item.weekly_change_pct, 2),
        _number(None if item.trading_value is None else item.trading_value / 100_000_000, 1),
        _number(item.open), _number(item.high), _number(item.low), _number(item.volume), item.market,
        _number(None if item.market_cap is None else item.market_cap / 100_000_000, 1),
    )
    return values if include_date else values[1:]
