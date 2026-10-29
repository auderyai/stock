from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from krx_research_nextgen.models.screening import ScreeningResult
FIELDS = (
    "trade_date", "rank", "stock_code", "stock_name", "industry", "close",
    "change_pct", "weekly_change_pct", "trading_value_eok", "open", "high",
    "low", "volume", "market", "market_cap_eok",
)
HEADERS = (
    "기준일", "순위", "종목코드", "종목명", "업종", "종가", "일간(%)", "주간(%)",
    "거래대금(억원)", "시가", "고가", "저가", "거래량", "시장", "시가총액(억원)",
)
HIGH_52W_FIELDS = ("high_52w", "distance_from_high_pct")
LABELS = dict(zip(
    FIELDS + HIGH_52W_FIELDS,
    HEADERS + ("52주 최고 고가", "52주 최고가 대비 종가(%)"),
    strict=True,
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
    detail = HIGH_52W_FIELDS if any(item.high_52w is not None for item in rows) else ()
    return pd.DataFrame(records, columns=FIELDS + detail)
