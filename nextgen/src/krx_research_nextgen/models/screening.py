from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class ScreeningKind(str, Enum):
    EMA_SIMILARITY = "이동평균 유사배열"
    HIGH_52W = "52주 신고가"
    NEAR_HIGH_52W = "52주 최고가 대비 종가 구간"
    BOLLINGER_BREAKOUT = "주봉 볼린저 돌파"
    DAILY_GAINERS = "당일 상승률 TOP"
    WEEKLY_GAINERS = "주간 상승률 TOP"
    TURNOVER_TOP = "거래대금 TOP"
    WEEKLY_TURNOVER_TOP = "주간 거래대금 TOP"
    EMA20_LEADING_SECTOR = "20일선+주도섹터"


@dataclass(frozen=True)
class ScreeningQuery:
    kind: ScreeningKind
    limit: int = 100
    market: str = "ALL"
    comparison_ticker: str = "005930"
    near_low: float = -10.0
    near_high: float = 0.0
    as_of_date: str | None = None
    source_mode: str = "database"
    quote_venue: str = "KRX"


@dataclass(frozen=True)
class ScreeningResult:
    stock_code: str
    stock_name: str
    market: str
    trade_date: str
    close: float
    change_pct: float | None = None
    trading_value: float | None = None
    high_52w: float | None = None
    distance_from_high_pct: float | None = None
    rank: int = 0
    industry: str = ""
    weekly_change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    market_cap: float | None = None


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")


@dataclass(frozen=True)
class RepeatedScreenResult:
    appearance_count: int
    stock_code: str
    stock_name: str
    industry: str
    screen_dates: tuple[str, ...]
    average_daily_pct: float | None
    maximum_daily_pct: float | None
    average_weekly_pct: float | None
    maximum_weekly_pct: float | None
    latest_trading_value: float | None
    latest_close: float | None
