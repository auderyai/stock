"""Read-only GUI data models backed by the configured KRX store."""

from __future__ import annotations

import datetime as dt
import io
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics import (
    EMA_WINDOWS,
    build_market_screens,
    calculate_technical_indicators,
    exclude_spac_securities,
)
from krx_research.collectors.index_membership import (
    INDEX_GAINER_DEFINITIONS,
    INDEX_GAINER_SCREEN_TYPES,
    IndexMembership,
    fetch_index_membership,
)
from krx_research.collectors.market_data import normalize_ticker
from krx_research.collectors.realtime_quotes import (
    QUOTE_VENUE_KRX,
    QUOTE_VENUES,
    RealtimeQuoteSnapshot,
    fetch_realtime_krx_quotes,
)
from krx_research.database import (
    DatabaseTarget,
    PostgreSQLSettings,
    open_research_store,
)
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.data_engine.investor import FOREIGN_MEMBERS, INSTITUTION_MEMBERS
from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY

from .on_demand import PostgreSQLOnDemandData

SCREEN_TITLES = {
    "ema_similarity": "이동평균 유사배열",
    "high_52w": "당일 52주 신고가",
    "near_high_52w": "52주 최고가 대비 종가 구간",
    "bollinger_breakout": "주봉 볼린저 돌파",
    "kospi_weekly_gainers": "KOSPI 주간 상승률 Top",
    "kosdaq_weekly_gainers": "KOSDAQ 주간 상승률 Top",
    "weekly_return": "KOSPI+KOSDAQ 주간 상승률 Top",
    "kospi200_daily_gainers": "KOSPI 200 당일 상승률 Top",
    "kosdaq150_daily_gainers": "KOSDAQ 150 당일 상승률 Top",
    "kospi200_kosdaq150_daily_gainers": "KOSPI 200+KOSDAQ 150 당일 상승률 Top",
    "kospi200_weekly_gainers": "KOSPI 200 주간 상승률 Top",
    "kosdaq150_weekly_gainers": "KOSDAQ 150 주간 상승률 Top",
    "kospi200_kosdaq150_weekly_gainers": "KOSPI 200+KOSDAQ 150 주간 상승률 Top",
    "kospi_daily_gainers": "KOSPI 전체 당일 상승률 Top",
    "kosdaq_daily_gainers": "KOSDAQ 전체 당일 상승률 Top",
    "kospi_kosdaq_daily_gainers": "KOSPI+KOSDAQ 당일 상승률 Top",
    "kospi_kosdaq_daily_trading_value": "KOSPI+KOSDAQ 당일 거래대금 Top",
    "kospi_weekly_trading_value": "KOSPI 거래대금 주간 Top",
    "kosdaq_weekly_trading_value": "KOSDAQ 거래대금 주간 Top",
    "kospi_kosdaq_weekly_trading_value": "KOSPI+KOSDAQ 거래대금 주간 Top",
}

INVESTOR_FLOW_SCREEN_DEFINITIONS = {
    f"{market.lower()}_{investor}_net_{direction}": (market, investor, direction)
    for market in ("KOSPI", "KOSDAQ")
    for investor in ("foreign", "institution", "individual")
    for direction in ("buy", "sell")
}
_INVESTOR_NAMES = {"foreign": "외국인", "institution": "기관", "individual": "개인"}
# Investor-flow Top10 results are exposed through the dedicated dashboard.
# Keep the definitions for data/service compatibility, but do not duplicate the
# 12 dashboard panels in the main workstation screen selector.

DATABASE_SOURCE_MODE = "database"
REALTIME_SOURCE_MODE = "realtime"
DATA_SOURCE_MODES = frozenset({DATABASE_SOURCE_MODE, REALTIME_SOURCE_MODE})


class DatabaseDateMismatchError(ValueError):
    """The selected screening date has not been recorded in the database."""


MARKET_GAINER_DEFINITIONS = {
    "kospi_daily_gainers": "KOSPI",
    "kosdaq_daily_gainers": "KOSDAQ",
    "kospi_kosdaq_daily_gainers": "KOSPI+KOSDAQ",
}
MARKET_GAINER_SCREEN_TYPES = frozenset(MARKET_GAINER_DEFINITIONS)
MARKET_WEEKLY_GAINER_DEFINITIONS = {
    "weekly_return": "KOSPI+KOSDAQ",
    "kospi_weekly_gainers": "KOSPI",
    "kosdaq_weekly_gainers": "KOSDAQ",
}
MARKET_WEEKLY_GAINER_SCREEN_TYPES = frozenset(MARKET_WEEKLY_GAINER_DEFINITIONS)
MARKET_TRADING_VALUE_DEFINITIONS = {
    "kospi_kosdaq_daily_trading_value": "KOSPI+KOSDAQ",
}
WEEKLY_TRADING_VALUE_DEFINITIONS = {
    "kospi_weekly_trading_value": "KOSPI",
    "kosdaq_weekly_trading_value": "KOSDAQ",
    "kospi_kosdaq_weekly_trading_value": "KOSPI+KOSDAQ",
}
WEEKLY_TRADING_VALUE_SCREEN_TYPES = frozenset(WEEKLY_TRADING_VALUE_DEFINITIONS)
MARKET_TRADING_VALUE_SCREEN_TYPES = frozenset(MARKET_TRADING_VALUE_DEFINITIONS)
MARKET_RESULT_DEFINITIONS = {
    **MARKET_GAINER_DEFINITIONS,
    **MARKET_WEEKLY_GAINER_DEFINITIONS,
    **MARKET_TRADING_VALUE_DEFINITIONS,
    **WEEKLY_TRADING_VALUE_DEFINITIONS,
}
MARKET_RESULT_SCREEN_TYPES = frozenset(MARKET_RESULT_DEFINITIONS)
INDEX_DAILY_MEMBERSHIP_TYPES = {
    "kospi200_kosdaq150_daily_gainers": (
        "kospi200_daily_gainers",
        "kosdaq150_daily_gainers",
    ),
}
INDEX_WEEKLY_MEMBERSHIP_TYPES = {
    "kospi200_weekly_gainers": ("kospi200_daily_gainers",),
    "kosdaq150_weekly_gainers": ("kosdaq150_daily_gainers",),
    "kospi200_kosdaq150_weekly_gainers": (
        "kospi200_daily_gainers",
        "kosdaq150_daily_gainers",
    ),
}
INDEX_WEEKLY_SCREEN_TYPES = frozenset(INDEX_WEEKLY_MEMBERSHIP_TYPES)
INDEX_MEMBERSHIP_TYPES = {
    **INDEX_DAILY_MEMBERSHIP_TYPES,
    **INDEX_WEEKLY_MEMBERSHIP_TYPES,
}
INDEX_RELATED_SCREEN_TYPES = frozenset(
    set(INDEX_GAINER_SCREEN_TYPES) | set(INDEX_MEMBERSHIP_TYPES)
)
WEEKLY_SCREEN_TYPES = frozenset({"bollinger_breakout", *MARKET_WEEKLY_GAINER_SCREEN_TYPES, *INDEX_WEEKLY_SCREEN_TYPES, *WEEKLY_TRADING_VALUE_SCREEN_TYPES})
DIRECT_ON_DEMAND_SCREEN_TYPES = frozenset(SCREEN_TITLES)
INVESTOR_FLOW_SCREEN_TYPES = frozenset(INVESTOR_FLOW_SCREEN_DEFINITIONS)
DAILY_GAINER_SCREEN_TYPES = frozenset(
    set(INDEX_GAINER_SCREEN_TYPES)
    | set(INDEX_DAILY_MEMBERSHIP_TYPES)
    | set(MARKET_GAINER_SCREEN_TYPES)
    | set(MARKET_TRADING_VALUE_SCREEN_TYPES)
)
REALTIME_CACHE_SECONDS = 60.0
REALTIME_ADJUSTMENT_RATIO_TOLERANCE = 0.02

RSI_PERIOD, RSI_SIGNAL_PERIOD = DEFAULT_CHART_ANALYSIS_POLICY.rsi.periods
STOCHASTIC_K_PERIOD, STOCHASTIC_K_SMOOTHING, STOCHASTIC_D_PERIOD = (
    DEFAULT_CHART_ANALYSIS_POLICY.stochastic_slow.periods
)
KST = ZoneInfo("Asia/Seoul")


def _market_values(screen_type: str) -> tuple[str, ...]:
    market_label = MARKET_RESULT_DEFINITIONS[screen_type]
    return tuple(value for value in market_label.split("+") if value)


def select_period_screen_dates(
    available: list[dt.date],
    *,
    start: dt.date,
    end: dt.date,
    screen_type: str,
) -> list[dt.date]:
    """Select stored dates using the screen's natural aggregation period."""

    selected = sorted(value for value in available if start <= value <= end)
    if screen_type not in WEEKLY_SCREEN_TYPES or not selected:
        return selected
    dated = pd.DataFrame({"screen_date": pd.to_datetime(selected)})
    dated["screen_week"] = dated["screen_date"].dt.to_period("W-FRI")
    return [
        value.date()
        for value in dated.groupby("screen_week", sort=True)["screen_date"].max()
    ]


@dataclass(frozen=True)
class ScreenDataset:
    screen_type: str
    title: str
    run: dict[str, Any]
    rows: DataFrame
    latest_price_date: dt.date | None
    latest_indicator_date: dt.date | None


def filter_52w_distance(
    screen: ScreenDataset, lower_pct: float, upper_pct: float,
) -> ScreenDataset:
    """Include both signed percentage endpoints and keep the displayed rank contiguous."""

    lower = float(lower_pct)
    upper = float(upper_pct)
    if not np.isfinite(lower) or not np.isfinite(upper) or lower > upper:
        raise ValueError("구간은 유한한 숫자로 입력하고, 시작값은 종료값 이하로 지정하세요.")
    if screen.screen_type != "near_high_52w":
        raise ValueError("52주 최고가 대비 종가 화면에서만 사용할 수 있습니다.")
    values = pd.to_numeric(
        screen.rows.get(
            "distance_from_52w_high_pct",
            pd.Series(index=screen.rows.index, dtype="float64"),
        ), errors="coerce",
    ).round(6)
    rows = screen.rows.loc[values.ge(lower) & values.le(upper)].copy()
    if "screen_date" in rows.columns:
        rows["rank"] = rows.groupby("screen_date", sort=False).cumcount() + 1
    else:
        rows["rank"] = np.arange(1, len(rows) + 1)
    run = dict(screen.run)
    run.update(distance_lower_pct=lower, distance_upper_pct=upper)
    return replace(screen, rows=rows.reset_index(drop=True), run=run)


def describe_screen_freshness(
    dataset: ScreenDataset,
    *,
    today: dt.date | None = None,
) -> str:
    """Describe exactly which persisted stage limits the displayed date."""

    current_date = today or dt.datetime.now(tz=KST).date()
    screen_date = pd.Timestamp(dataset.run["as_of_date"]).date()
    price_date = dataset.latest_price_date
    indicator_date = dataset.latest_indicator_date
    if dataset.screen_type in INVESTOR_FLOW_SCREEN_TYPES:
        return (
            f"확정 수급 {screen_date.isoformat()} · DB 일봉 마지막 "
            f"{price_date.isoformat() if price_date else '없음'}"
        )
    if dataset.run.get("data_source_mode") == REALTIME_SOURCE_MODE:
        retrieved_at = str(dataset.run.get("retrieved_at") or "시각 미표시")
        source = str(dataset.run.get("source") or "공급원 미표시")
        adjusted_count = int(dataset.run.get("adjusted_reference_count") or 0)
        adjustment_text = (
            f" · 자본변동 가격기준 보정 {adjusted_count:,}종목"
            if adjusted_count
            else ""
        )
        return (
            f"실시간 가격 {screen_date.isoformat()} · 수집 {retrieved_at} · "
            f"공급원 {source} · DB 지표 "
            f"{indicator_date.isoformat() if indicator_date else '없음'}"
            f"{adjustment_text}"
        )
    dates = (
        f"스크린 {screen_date.isoformat()} · "
        f"지표 {indicator_date.isoformat() if indicator_date else '없음'} · "
        f"가격 {price_date.isoformat() if price_date else '없음'}"
    )
    if price_date is None:
        return f"{dates} · 가격자료가 없습니다."
    if indicator_date is None or indicator_date < price_date:
        return f"{dates} · 기술지표 재계산이 필요합니다."
    if screen_date < indicator_date:
        return f"{dates} · 스크리닝 재실행이 필요합니다."
    if screen_date < current_date:
        return (
            f"{dates} · 오늘 {current_date.isoformat()} 자료가 아직 없습니다"
            "(장 마감 전 또는 휴장일이면 정상)."
        )
    return f"{dates} · 최신 상태입니다."


@dataclass(frozen=True)
class ChartDataset:
    ticker: str
    name: str
    market: str
    industry: str
    daily: DataFrame
    weekly: DataFrame
    monthly: DataFrame = field(default_factory=DataFrame)
    quarterly: DataFrame = field(default_factory=DataFrame)
    yearly: DataFrame = field(default_factory=DataFrame)
    investor: dict[str, DataFrame] = field(default_factory=dict)
    loaded_timeframes: frozenset[str] = field(default_factory=frozenset)
    investor_loaded: bool = False

    def bars(self, timeframe: str) -> DataFrame:
        """Return one D/W/M/Q/Y frame while retaining the legacy fields."""

        key = str(timeframe).strip().upper()
        frames = {
            "D": self.daily,
            "W": self.weekly,
            "M": self.monthly,
            "Q": self.quarterly,
            "Y": self.yearly,
        }
        try:
            return frames[key]
        except KeyError as error:
            raise ValueError(f"지원하지 않는 봉 주기: {timeframe!r}") from error

    def investor_flow(self, timeframe: str) -> DataFrame:
        key = str(timeframe).strip().upper()
        return self.investor.get(key, DataFrame()).copy()


def build_index_gainer_rows(
    snapshot: DataFrame,
    membership: IndexMembership,
    *,
    limit: int = 30,
) -> DataFrame:
    """Rank one dated index cross-section by daily return, deterministically."""

    if limit < 1:
        raise ValueError("limit must be positive")
    required = {
        "ticker",
        "trade_date",
        "close",
        "daily_return_pct",
        "estimated_trading_value",
    }
    if missing := required.difference(snapshot.columns):
        raise ValueError(f"Index-gainer snapshot missing columns: {sorted(missing)}")

    frame = exclude_spac_securities(snapshot)
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["daily_return_pct"] = pd.to_numeric(frame["daily_return_pct"], errors="coerce")
    frame["estimated_trading_value"] = pd.to_numeric(
        frame["estimated_trading_value"], errors="coerce"
    )
    frame = frame.loc[
        frame["ticker"].isin(membership.tickers) & frame["daily_return_pct"].notna()
    ].copy()
    frame = frame.sort_values(
        ["daily_return_pct", "estimated_trading_value", "ticker"],
        ascending=[False, False, True],
        na_position="last",
        kind="mergesort",
    ).head(limit)
    frame = frame.reset_index(drop=True)
    frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype="int64"))
    frame.insert(1, "screen_type", membership.screen_type)
    return frame


def build_index_weekly_gainer_rows(
    snapshot: DataFrame,
    membership: IndexMembership,
    *,
    limit: int = 30,
) -> DataFrame:
    """Rank one or two index universes by current-week return."""

    if limit < 1:
        raise ValueError("limit must be positive")
    required = {
        "ticker",
        "trade_date",
        "close",
        "weekly_return_pct",
        "estimated_trading_value",
    }
    if missing := required.difference(snapshot.columns):
        raise ValueError(f"Index weekly-gainer snapshot missing columns: {sorted(missing)}")

    frame = exclude_spac_securities(snapshot)
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["weekly_return_pct"] = pd.to_numeric(
        frame["weekly_return_pct"], errors="coerce"
    )
    frame["estimated_trading_value"] = pd.to_numeric(
        frame["estimated_trading_value"], errors="coerce"
    )
    frame = frame.loc[
        frame["ticker"].isin(membership.tickers)
        & frame["weekly_return_pct"].notna()
    ].copy()
    frame = frame.sort_values(
        ["weekly_return_pct", "estimated_trading_value", "ticker"],
        ascending=[False, False, True],
        na_position="last",
        kind="mergesort",
    ).head(limit)
    frame = frame.reset_index(drop=True)
    frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype="int64"))
    frame.insert(1, "screen_type", membership.screen_type)
    return frame


def build_market_gainer_rows(
    snapshot: DataFrame,
    screen_type: str,
    *,
    limit: int = 50,
) -> DataFrame:
    """Rank a complete KOSPI or KOSDAQ cross-section by daily return."""

    if limit < 1:
        raise ValueError("limit must be positive")
    try:
        market = MARKET_GAINER_DEFINITIONS[screen_type]
    except KeyError as error:
        raise ValueError(f"Unsupported market-gainer screen: {screen_type!r}") from error
    required = {
        "ticker",
        "market",
        "trade_date",
        "close",
        "daily_return_pct",
        "estimated_trading_value",
    }
    if missing := required.difference(snapshot.columns):
        raise ValueError(f"Market-gainer snapshot missing columns: {sorted(missing)}")

    frame = exclude_spac_securities(snapshot)
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["market"] = frame["market"].astype("string").str.upper().str.strip()
    frame["daily_return_pct"] = pd.to_numeric(
        frame["daily_return_pct"], errors="coerce"
    )
    frame["estimated_trading_value"] = pd.to_numeric(
        frame["estimated_trading_value"], errors="coerce"
    )
    markets = tuple(value for value in market.split("+") if value)
    frame = frame.loc[
        frame["market"].isin(markets) & frame["daily_return_pct"].notna()
    ].copy()
    frame = frame.sort_values(
        ["daily_return_pct", "estimated_trading_value", "ticker"],
        ascending=[False, False, True],
        na_position="last",
        kind="mergesort",
    ).head(limit)
    frame = frame.reset_index(drop=True)
    frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype="int64"))
    frame.insert(1, "screen_type", screen_type)
    return frame


def build_market_trading_value_rows(
    snapshot: DataFrame,
    screen_type: str,
    *,
    limit: int = 100,
) -> DataFrame:
    """Rank KOSPI and KOSDAQ stocks by the day's trading value."""

    if limit < 1:
        raise ValueError("limit must be positive")
    try:
        market = MARKET_TRADING_VALUE_DEFINITIONS[screen_type]
    except KeyError as error:
        raise ValueError(
            f"Unsupported market trading-value screen: {screen_type!r}"
        ) from error
    required = {
        "ticker",
        "market",
        "trade_date",
        "close",
        "daily_return_pct",
        "estimated_trading_value",
    }
    if missing := required.difference(snapshot.columns):
        raise ValueError(
            f"Market trading-value snapshot missing columns: {sorted(missing)}"
        )

    frame = exclude_spac_securities(snapshot)
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["market"] = frame["market"].astype("string").str.upper().str.strip()
    frame["daily_return_pct"] = pd.to_numeric(
        frame["daily_return_pct"], errors="coerce"
    )
    frame["estimated_trading_value"] = pd.to_numeric(
        frame["estimated_trading_value"], errors="coerce"
    )
    markets = tuple(value for value in market.split("+") if value)
    frame = frame.loc[
        frame["market"].isin(markets)
        & frame["estimated_trading_value"].notna()
        & frame["estimated_trading_value"].ge(0)
    ].copy()
    frame = frame.sort_values(
        ["estimated_trading_value", "daily_return_pct", "ticker"],
        ascending=[False, False, True],
        na_position="last",
        kind="mergesort",
    ).head(limit)
    frame = frame.reset_index(drop=True)
    frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype="int64"))
    frame.insert(1, "screen_type", screen_type)
    return frame


def build_market_result_rows(snapshot: DataFrame, screen_type: str) -> DataFrame:
    """Dispatch a whole-market daily screen to its requested ranking metric."""

    if screen_type in MARKET_GAINER_SCREEN_TYPES:
        return build_market_gainer_rows(snapshot, screen_type, limit=len(snapshot))
    if screen_type in MARKET_WEEKLY_GAINER_SCREEN_TYPES:
        market = MARKET_WEEKLY_GAINER_DEFINITIONS[screen_type]
        frame = exclude_spac_securities(snapshot).copy()
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
        frame["market"] = frame["market"].astype("string").str.upper().str.strip()
        frame["weekly_return_pct"] = pd.to_numeric(frame["weekly_return_pct"], errors="coerce")
        frame["estimated_trading_value"] = pd.to_numeric(frame["estimated_trading_value"], errors="coerce")
        markets = tuple(value for value in market.split("+") if value)
        frame = frame.loc[
            frame["market"].isin(markets) & frame["weekly_return_pct"].notna()
        ].copy()
        frame = frame.sort_values(
            ["weekly_return_pct", "estimated_trading_value", "ticker"],
            ascending=[False, False, True],
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)
        frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype="int64"))
        frame.insert(1, "screen_type", screen_type)
        return frame
    if screen_type in MARKET_TRADING_VALUE_SCREEN_TYPES:
        return build_market_trading_value_rows(snapshot, screen_type, limit=len(snapshot))
    if screen_type in WEEKLY_TRADING_VALUE_SCREEN_TYPES:
        market = WEEKLY_TRADING_VALUE_DEFINITIONS[screen_type]
        frame = exclude_spac_securities(snapshot).copy()
        frame["market"] = frame["market"].astype("string").str.upper().str.strip()
        markets = tuple(value for value in market.split("+") if value)
        frame = frame.loc[frame["market"].isin(markets) & frame["weekly_trading_value_eok"].notna()].copy()
        frame = frame.sort_values(["weekly_trading_value_eok", "ticker"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
        frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype="int64"))
        frame.insert(1, "screen_type", screen_type)
        return frame
    raise ValueError(f"Unsupported market result screen: {screen_type!r}")


def build_investor_flow_rows(
    flow: DataFrame,
    master: DataFrame,
    prices: DataFrame,
    screen_type: str,
    *,
    limit: int = 10,
) -> DataFrame:
    """Rank actual net cash flows; positive buys and negative sells stay signed."""

    if limit < 1:
        raise ValueError("limit must be positive")
    market, investor, direction = INVESTOR_FLOW_SCREEN_DEFINITIONS[screen_type]
    codes = {
        "foreign": FOREIGN_MEMBERS,
        "institution": INSTITUTION_MEMBERS,
        "individual": ("INDIVIDUAL",),
    }[investor]
    required_flow = {"stock_code", "investor_type", "buy_value", "sell_value"}
    if missing := required_flow.difference(flow.columns):
        raise ValueError(f"수급 자료에 필요한 열이 없습니다: {sorted(missing)}")
    required_master = {"stock_code", "stock_name", "market"}
    if missing := required_master.difference(master.columns):
        raise ValueError(f"종목 자료에 필요한 열이 없습니다: {sorted(missing)}")
    facts = flow.loc[flow["investor_type"].isin(codes)].copy()
    for column in ("buy_value", "sell_value"):
        facts[column] = pd.to_numeric(facts[column], errors="coerce")
    facts = facts.dropna(subset=["buy_value", "sell_value"])
    facts = facts.groupby("stock_code", as_index=False)[["buy_value", "sell_value"]].sum()
    securities = master.copy()
    securities["market"] = securities["market"].astype("string").str.upper().str.strip()
    securities = securities.loc[securities["market"].eq(market)].drop_duplicates("stock_code")
    securities = securities.rename(columns={"stock_code": "ticker", "stock_name": "name"})
    facts = facts.rename(columns={"stock_code": "ticker"})
    rows = securities.merge(facts, on="ticker", how="inner", validate="1:1")
    rows = exclude_spac_securities(rows)
    rows["investor_net_value"] = rows["buy_value"] - rows["sell_value"]
    rows = rows.loc[
        rows["investor_net_value"].gt(0)
        if direction == "buy" else rows["investor_net_value"].lt(0)
    ].copy()
    rows = rows.sort_values(
        ["investor_net_value", "ticker"],
        ascending=[direction == "sell", True],
        kind="mergesort",
    ).head(limit).reset_index(drop=True)
    close = prices[["stock_code", "close_price"]].copy() if not prices.empty else pd.DataFrame(
        columns=["stock_code", "close_price"]
    )
    close = close.drop_duplicates("stock_code", keep="last").rename(
        columns={"stock_code": "ticker", "close_price": "close"}
    )
    rows = rows.merge(close, on="ticker", how="left", validate="1:1")
    rows.insert(0, "rank", np.arange(1, len(rows) + 1))
    rows.insert(1, "screen_type", screen_type)
    return rows


def overlay_realtime_quotes(
    database_snapshot: DataFrame,
    quote_snapshot: RealtimeQuoteSnapshot,
) -> DataFrame:
    """Overlay current KRX quotes on the latest persisted indicator snapshot."""

    database_required = {
        "ticker",
        "name",
        "market",
        "trade_date",
        "close",
        "prior_high_52w",
        "high_52w",
        "formula_version",
        "weekly_previous_close",
        "weekly_high",
        "weekly_close",
        "week_end",
        "bb_upper_20_2",
    }
    if missing := database_required.difference(database_snapshot.columns):
        raise ValueError(
            f"Database indicator snapshot missing columns: {sorted(missing)}"
        )
    if database_snapshot.empty:
        raise ValueError("Database indicator snapshot is empty")

    quotes = quote_snapshot.rows.rename(
        columns={
            "name": "live_name",
            "market": "live_market",
            "trade_date": "live_trade_date",
            "open": "live_open",
            "high": "live_high",
            "low": "live_low",
            "close": "live_close",
            "volume": "live_volume",
            "trading_value": "live_trading_value",
            "daily_return_pct": "live_daily_return_pct",
        }
    )
    frame = database_snapshot.merge(quotes, on="ticker", how="inner", validate="1:1")
    if frame.empty:
        raise ValueError("실시간 시세와 DB 기술지표가 일치하는 종목이 없습니다.")

    database_dates = pd.to_datetime(frame["trade_date"]).dt.normalize()
    live_dates = pd.to_datetime(frame["live_trade_date"]).dt.normalize()
    database_close = pd.to_numeric(frame["close"], errors="coerce")
    live_close = pd.to_numeric(frame["live_close"], errors="coerce")
    live_return = pd.to_numeric(frame["live_daily_return_pct"], errors="coerce")
    return_denominator = 1.0 + live_return.div(100.0)
    implied_previous_close = live_close.div(
        return_denominator.where(return_denominator.gt(0))
    )
    reference_ratio = implied_previous_close.div(database_close.replace(0, np.nan))
    future_rows = live_dates.gt(database_dates)
    corporate_action = (
        future_rows
        & reference_ratio.notna()
        & np.isfinite(reference_ratio)
        & reference_ratio.gt(0)
        & reference_ratio.sub(1.0).abs().ge(
            REALTIME_ADJUSTMENT_RATIO_TOLERANCE
        )
    )
    reference_factor = pd.Series(1.0, index=frame.index, dtype="float64")
    reference_factor.loc[corporate_action] = reference_ratio.loc[corporate_action]
    frame["reference_price_adjustment_factor"] = reference_factor
    for column in (
        "prior_high_52w",
        "high_52w",
        "weekly_previous_close",
        "weekly_high",
        "weekly_close",
        "bb_upper_20_2",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").mul(
            reference_factor
        )
    frame["name"] = frame["name"].fillna(frame["live_name"])
    frame["market"] = frame["live_market"].fillna(frame["market"])
    frame["trade_date"] = live_dates
    frame["open"] = frame["live_open"]
    frame["high"] = frame["live_high"]
    frame["low"] = frame["live_low"]
    frame["close"] = frame["live_close"]
    frame["volume"] = frame["live_volume"].astype("int64")
    frame["estimated_trading_value"] = frame["live_trading_value"]
    frame["daily_return_pct"] = frame["live_daily_return_pct"]

    previous_high = frame["prior_high_52w"].copy()
    previous_high.loc[future_rows] = frame.loc[future_rows, "high_52w"]
    previous_high = pd.to_numeric(previous_high, errors="coerce")
    # Always keep the actual stored high as the minimum comparison threshold.
    # A quote-return mismatch is not reliable proof of a split or other
    # corporate action, especially for thinly traded preferred shares.  It
    # must never erase a real high and manufacture a false 52-week breakout.
    if {"prior_source_high_52w", "source_high_52w"}.issubset(frame.columns):
        source_prior = pd.to_numeric(frame["prior_source_high_52w"], errors="coerce")
        source_prior.loc[future_rows] = pd.to_numeric(
            frame.loc[future_rows, "source_high_52w"], errors="coerce"
        )
        previous_high = pd.concat([previous_high, source_prior], axis=1).max(axis=1)
    live_high = pd.to_numeric(frame["live_high"], errors="coerce")
    frame["prior_high_52w"] = previous_high
    frame["high_52w"] = pd.concat([previous_high, live_high], axis=1).max(axis=1)
    frame["distance_from_52w_high_pct"] = (
        frame["close"] / frame["high_52w"] - 1.0
    ) * 100.0
    available_high = frame["high_52w"].notna()
    frame["is_52w_high"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    frame.loc[available_high, "is_52w_high"] = (
        live_high.loc[available_high] >= frame.loc[available_high, "high_52w"]
    ).astype("int64")
    frame["is_52w_breakout"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    available_prior = previous_high.notna()
    frame.loc[available_prior, "is_52w_breakout"] = (
        live_high.loc[available_prior] > previous_high.loc[available_prior]
    ).astype("int64")

    live_week_end = live_dates.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    stored_week_end = pd.to_datetime(frame["week_end"]).dt.normalize()
    same_week = live_week_end.eq(stored_week_end)
    prior_week_close = pd.to_numeric(frame["weekly_close"], errors="coerce")
    prior_week_close.loc[same_week] = pd.to_numeric(
        frame.loc[same_week, "weekly_previous_close"], errors="coerce"
    )
    frame["weekly_return_pct"] = (
        frame["close"] / prior_week_close.replace(0, np.nan) - 1.0
    ) * 100.0
    frame["week_end"] = live_week_end
    frame["weekly_last_trade_date"] = live_dates
    frame["weekly_close"] = frame["close"]
    band = pd.to_numeric(frame["bb_upper_20_2"], errors="coerce")
    frame["is_bb_upper_breakout"] = pd.Series(
        pd.NA, index=frame.index, dtype="Int64"
    )
    available_band = band.notna()
    frame.loc[available_band, "is_bb_upper_breakout"] = (
        frame.loc[available_band, "close"] > band.loc[available_band]
    ).astype("int64")
    frame["quote_source"] = quote_snapshot.source
    return frame.drop(
        columns=[column for column in frame if column.startswith("live_")],
    )


class WorkstationData:
    """Open short-lived readers so chart workers never share connections."""

    def __init__(
        self,
        database_target: DatabaseTarget,
        *,
        index_membership_fetcher: Callable[[str, object], IndexMembership] = (
            fetch_index_membership
        ),
        realtime_quote_fetcher: Callable[..., RealtimeQuoteSnapshot] = (
            fetch_realtime_krx_quotes
        ),
        realtime_cache_seconds: float = REALTIME_CACHE_SECONDS,
    ) -> None:
        if realtime_cache_seconds < 0:
            raise ValueError("realtime_cache_seconds must not be negative")
        self.database_target = database_target
        self.index_membership_fetcher = index_membership_fetcher
        self.realtime_quote_fetcher = realtime_quote_fetcher
        self.realtime_cache_seconds = float(realtime_cache_seconds)
        self._index_membership_cache: dict[tuple[str, dt.date], IndexMembership] = {}
        self._realtime_cache: tuple[
            str,
            float,
            RealtimeQuoteSnapshot,
            DataFrame,
            dt.date,
        ] | None = None
        self._realtime_cache_lock = threading.Lock()
        self._on_demand = (
            PostgreSQLOnDemandData(database_target)
            if isinstance(database_target, PostgreSQLSettings)
            else None
        )


    def available_screen_dates(
        self, limit: int = 500, *, quote_venue: str = QUOTE_VENUE_KRX
    ) -> list[dt.date]:
        """Return selectable PostgreSQL trading dates, newest first."""

        if self._on_demand is not None:
            with BaseDataRepository(self._on_demand.settings) as repository:
                if quote_venue != QUOTE_VENUE_KRX:
                    return repository.available_venue_ohlcv_dates(quote_venue, limit=limit)
                return repository.available_ohlcv_dates(
                    adjusted_only=True,
                    limit=limit,
                )
        with open_research_store(self.database_target, read_only=True) as store:
            method = getattr(store, "available_ohlcv_dates", None)
            if callable(method):
                return list(method(adjusted_only=True, limit=limit))
            latest = store.latest_adjusted_ohlcv_date()
        return [] if latest is None else [latest]

    def latest_screen_date(self, *, quote_venue: str = QUOTE_VENUE_KRX) -> dt.date | None:
        """Return a usable default even when the distinct-date list fails."""

        if self._on_demand is not None:
            with BaseDataRepository(self._on_demand.settings) as repository:
                if quote_venue != QUOTE_VENUE_KRX:
                    return repository.latest_venue_ohlcv_date(quote_venue)
                return repository.latest_ohlcv_date()
        with open_research_store(self.database_target, read_only=True) as store:
            method = getattr(store, "latest_adjusted_ohlcv_date", None)
            return method() if callable(method) else None

    def load_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None = None,
        data_source_mode: str = DATABASE_SOURCE_MODE,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
        comparison_ticker: str | None = None,
    ) -> ScreenDataset:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()
        if screen_type not in SCREEN_TITLES:
            raise ValueError(f"Unsupported screen type: {screen_type!r}")
        if data_source_mode not in DATA_SOURCE_MODES:
            raise ValueError(f"Unsupported data source mode: {data_source_mode!r}")
        quote_venue = str(quote_venue).strip().upper()
        if quote_venue not in QUOTE_VENUES:
            raise ValueError(f"Unsupported quote venue: {quote_venue!r}")
        if screen_type == "ema_similarity":
            data_source_mode = DATABASE_SOURCE_MODE
        if screen_type in INVESTOR_FLOW_SCREEN_TYPES:
            if data_source_mode != DATABASE_SOURCE_MODE:
                raise ValueError("수급 거래대금은 DB에 저장된 확정 수급자료로 조회하십시오.")
            return self._load_investor_flow_screen(screen_type, as_of_date=as_of_date)
        if screen_type == "near_high_52w" and self._on_demand is None:
            raise ValueError("52주 고가 대비 종가 검색에는 PostgreSQL 일봉 원천자료가 필요합니다.")
        if data_source_mode == REALTIME_SOURCE_MODE and screen_type in WEEKLY_TRADING_VALUE_SCREEN_TYPES:
            raise ValueError("주간 거래대금 순위는 PostgreSQL 데이터베이스 모드에서 조회하십시오.")
        if data_source_mode == REALTIME_SOURCE_MODE:
            result = self._load_realtime_screen(
                screen_type,
                as_of_date=as_of_date,
                quote_venue=quote_venue,
            )
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            return result
        if self._on_demand is not None and screen_type in DIRECT_ON_DEMAND_SCREEN_TYPES:
            return self._load_on_demand_screen(
                screen_type,
                as_of_date=as_of_date,
                quote_venue=quote_venue,
                cancel_event=cancel_event,
                comparison_ticker=comparison_ticker,
            )
        if screen_type in MARKET_RESULT_SCREEN_TYPES:
            return self._load_database_market_gainer_screen(
                screen_type,
                as_of_date=as_of_date,
            )
        if screen_type in INDEX_RELATED_SCREEN_TYPES:
            return self._load_index_gainer_screen(
                screen_type,
                as_of_date=as_of_date,
            )
        with open_research_store(self.database_target, read_only=True) as store:
            rows = store.get_screen_results(screen_type, as_of_date=as_of_date)
            latest_price_date = store.latest_adjusted_ohlcv_date()
            latest_indicator_date = store.latest_technical_indicator_date()
        run = rows.attrs.get("screen_run")
        if run is None:
            raise ValueError("저장된 스크리닝 결과가 없습니다. 일일 파이프라인을 먼저 실행하세요.")
        rows = exclude_spac_securities(rows)
        run_details = dict(run)
        run_details["source"] = "DATABASE"
        run_details["data_source_mode"] = DATABASE_SOURCE_MODE
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run_details,
            rows=rows,
            latest_price_date=latest_price_date,
            latest_indicator_date=latest_indicator_date,
        )

    def load_screen_period(
        self,
        screen_type: str,
        *,
        start_date: object | None,
        end_date: object | None,
        data_source_mode: str = DATABASE_SOURCE_MODE,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
        comparison_ticker: str | None = None,
    ) -> ScreenDataset:
        """Load one or more stored trading dates and preserve each row's date."""

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()
        start = pd.Timestamp(start_date).date() if start_date is not None else None
        end = pd.Timestamp(end_date).date() if end_date is not None else None
        cancel_options: dict[str, object] = (
            {"cancel_event": cancel_event} if cancel_event is not None else {}
        )
        if start is None and end is None:
            dataset = self.load_screen(
                screen_type,
                as_of_date=None,
                data_source_mode=data_source_mode,
                quote_venue=quote_venue,
                comparison_ticker=comparison_ticker,
                **cancel_options,
            )
            rows = dataset.rows.copy()
            rows["screen_date"] = str(dataset.run.get("as_of_date", ""))
            return replace(dataset, rows=rows)
        start = start or end
        end = end or start
        if start is None or end is None:
            raise ValueError("조회 시작일과 종료일을 입력하십시오.")
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        if data_source_mode == REALTIME_SOURCE_MODE:
            # A current quote provider legitimately returns the computer's
            # current KST trading date.  Never constrain it with a stale DB
            # date left in the GUI selectors.
            today = dt.datetime.now(tz=KST).date()
            start = today
            end = today
        if screen_type in INVESTOR_FLOW_SCREEN_TYPES and data_source_mode != DATABASE_SOURCE_MODE:
            raise ValueError("수급 거래대금은 데이터베이스 모드에서 조회하십시오.")
        if data_source_mode == DATABASE_SOURCE_MODE:
            latest = self.latest_screen_date(quote_venue=quote_venue)
            if latest is None:
                raise DatabaseDateMismatchError(
                    "DB에 저장된 일봉 날짜가 없습니다. DB 갱신 후 조회 날짜를 다시 선택하세요."
                )
            if end > latest:
                raise DatabaseDateMismatchError(
                    f"선택한 종료일 {end.isoformat()}은 DB 마지막 갱신일 "
                    f"{latest.isoformat()}보다 늦습니다. 조회 날짜를 수정하거나 DB를 갱신하세요."
                )
        if start == end:
            dataset = self.load_screen(
                screen_type,
                as_of_date=end,
                data_source_mode=data_source_mode,
                quote_venue=quote_venue,
                comparison_ticker=comparison_ticker,
                **cancel_options,
            )
            rows = dataset.rows.copy()
            rows["screen_date"] = end.isoformat()
            run = dict(dataset.run)
            run.update(
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                date_count=1,
            )
            return replace(dataset, run=run, rows=rows)

        available = self.available_screen_dates(limit=5000, quote_venue=quote_venue)
        selected = select_period_screen_dates(
            available,
            start=start,
            end=end,
            screen_type=screen_type,
        )
        if not selected:
            raise ValueError("선택 기간에 저장된 영업일 자료가 없습니다.")
        datasets: list[ScreenDataset] = []
        frames: list[DataFrame] = []
        on_demand = getattr(self, "_on_demand", None)
        if on_demand is not None and screen_type not in INVESTOR_FLOW_SCREEN_TYPES:
            load_options: dict[str, object] = {}
            if cancel_event is not None:
                load_options["cancel_event"] = cancel_event
            if screen_type in DIRECT_ON_DEMAND_SCREEN_TYPES:
                computed_results = on_demand.load_screen_period(
                    screen_type,
                    selected,
                    comparison_ticker=comparison_ticker or "222800",
                    venue=quote_venue,
                    **load_options,
                )
            else:
                computed_results = on_demand.load_overlay_period(
                    selected,
                    **load_options,
                )
            period_membership = None
            if screen_type in INDEX_RELATED_SCREEN_TYPES and computed_results:
                newest = computed_results[-1]
                period_membership = self._membership_for_screen(
                    screen_type,
                    newest.as_of_date,
                    newest.rows,
                )
            source_datasets = [
                self._screen_dataset_from_on_demand(
                    screen_type,
                    computed,
                    quote_venue=quote_venue,
                    **(
                        {"membership": period_membership}
                        if period_membership is not None
                        else {}
                    ),
                )
                for computed in computed_results
            ]
        else:
            source_datasets = [
                self.load_screen(
                    screen_type,
                    as_of_date=screen_date,
                    data_source_mode=DATABASE_SOURCE_MODE,
                    comparison_ticker=comparison_ticker,
                )
                for screen_date in selected
            ]
        for screen_date, dataset in zip(selected, source_datasets, strict=True):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            frame = dataset.rows.copy()
            frame["screen_date"] = screen_date.isoformat()
            frames.append(frame)
            datasets.append(dataset)
        rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        newest = datasets[-1]
        run = dict(newest.run)
        run.update(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            date_count=len(selected),
            as_of_date=selected[-1].isoformat(),
            data_source_mode=DATABASE_SOURCE_MODE,
        )
        price_dates = [item.latest_price_date for item in datasets if item.latest_price_date]
        indicator_dates = [
            item.latest_indicator_date for item in datasets if item.latest_indicator_date
        ]
        return ScreenDataset(
            screen_type=screen_type,
            title=newest.title,
            run=run,
            rows=rows,
            latest_price_date=max(price_dates) if price_dates else None,
            latest_indicator_date=max(indicator_dates) if indicator_dates else None,
        )

    def _load_on_demand_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
        comparison_ticker: str | None = None,
    ) -> ScreenDataset:
        if self._on_demand is None:
            raise RuntimeError("PostgreSQL 온디맨드 엔진이 초기화되지 않았습니다.")
        computed = self._on_demand.load_screen(
            screen_type,
            as_of_date=as_of_date,
            venue=quote_venue,
            cancel_event=cancel_event,
            comparison_ticker=comparison_ticker or "222800",
        )
        return self._screen_dataset_from_on_demand(
            screen_type, computed, quote_venue=quote_venue
        )

    def _screen_dataset_from_on_demand(
        self,
        screen_type: str,
        computed: Any,
        *,
        membership: IndexMembership | None = None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> ScreenDataset:
        # LS_SCREEN_REPAIR_V2_ACTUAL_GUI_PATH
        if self._on_demand is not None and screen_type in (MARKET_RESULT_SCREEN_TYPES | INDEX_RELATED_SCREEN_TYPES):
            from krx_research.data_engine.screen_coverage import validate_screen_coverage
            markets = (MARKET_RESULT_DEFINITIONS[screen_type] if screen_type in MARKET_RESULT_SCREEN_TYPES
                       else self._index_market(screen_type)).split('+')
            minimum = 100 if screen_type in MARKET_TRADING_VALUE_SCREEN_TYPES else 50 if screen_type in MARKET_RESULT_SCREEN_TYPES or screen_type == 'kospi200_kosdaq150_daily_gainers' else 30
            with BaseDataRepository(self._on_demand.settings) as repository:
                validate_screen_coverage(repository, computed.as_of_date, computed.rows, markets, minimum=minimum)
            if screen_type in INDEX_RELATED_SCREEN_TYPES:
                membership = membership or self._membership_for_screen(screen_type, computed.as_of_date, computed.rows)
                with BaseDataRepository(self._on_demand.settings) as repository:
                    validate_screen_coverage(repository, computed.as_of_date, computed.rows, markets, membership, minimum)
        rows = computed.rows
        market = "ALL"
        matched_count = computed.universe_count
        constituent_count = computed.universe_count
        extra: dict[str, Any] = {}
        if screen_type in MARKET_RESULT_SCREEN_TYPES:
            rows = build_market_result_rows(rows, screen_type)
            market = MARKET_RESULT_DEFINITIONS[screen_type]
            markets = _market_values(screen_type)
            constituent_count = int(
                computed.rows["market"]
                .astype("string")
                .str.upper()
                .str.strip()
                .isin(markets)
                .sum()
            )
            matched_count = constituent_count
        elif screen_type in INDEX_RELATED_SCREEN_TYPES:
            membership = membership or self._membership_for_screen(
                screen_type, computed.as_of_date, computed.rows
            )
            rows = (
                build_index_weekly_gainer_rows(computed.rows, membership)
                if screen_type in INDEX_WEEKLY_SCREEN_TYPES
                else build_index_gainer_rows(
                    computed.rows,
                    membership,
                    limit=max(1, len(snapshot)),
                )
            )
            market = self._index_market(screen_type)
            constituent_count = len(membership.tickers)
            matched_count = int(
                computed.rows["ticker"].astype(str).isin(membership.tickers).sum()
            )
            extra = {
                "membership_source": membership.source,
                "index_code": membership.index_code,
                "index_name": membership.index_name,
                "constituent_as_of_date": membership.as_of_date.isoformat(),
            }
        generated_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
        run = {
            "run_id": (
                f"on-demand:{screen_type}:{computed.as_of_date.isoformat()}"
            ),
            "as_of_date": computed.as_of_date.isoformat(),
            "generated_at": generated_at,
            "source": "POSTGRESQL_BASE_ON_DEMAND",
            "data_source_mode": DATABASE_SOURCE_MODE,
            "quote_venue": quote_venue,
            "market": market,
            "constituent_count": constituent_count,
            "matched_count": matched_count,
            "positive_count": self._positive_count(rows, screen_type),
            **extra,
        }
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=computed.as_of_date,
            latest_indicator_date=computed.as_of_date,
        )

    def _database_snapshot(
        self,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> tuple[DataFrame, dt.date, dt.date | None]:
        if self._on_demand is not None:
            computed = self._on_demand.load_overlay_snapshot(
                as_of_date=as_of_date,
                venue=quote_venue,
            )
            return (
                computed.rows,
                computed.as_of_date,
                computed.as_of_date,
            )
        with open_research_store(self.database_target, read_only=True) as store:
            latest_price_date = store.latest_adjusted_ohlcv_date()
            screen_date = (
                store.latest_technical_indicator_date()
                if as_of_date is None
                else store.latest_technical_indicator_date(on_or_before=as_of_date)
            )
            if screen_date is None:
                raise ValueError("저장된 기술지표가 없습니다. 일일 파이프라인을 먼저 실행하세요.")
            snapshot = store.get_screen_snapshot(screen_date)
        return snapshot, screen_date, latest_price_date

    def _load_database_market_gainer_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
    ) -> ScreenDataset:
        snapshot, screen_date, latest_price_date = self._database_snapshot(as_of_date)
        market = MARKET_RESULT_DEFINITIONS[screen_type]
        markets = _market_values(screen_type)
        eligible = exclude_spac_securities(snapshot)
        market_count = int(
            eligible["market"]
            .astype("string")
            .str.upper()
            .str.strip()
            .isin(markets)
            .sum()
        )
        minimum = 100
        if market_count < minimum:
            raise ValueError(
                f"{screen_date.isoformat()} {market} DB 일봉은 {market_count}종목뿐입니다. "
                "당일 자료 수집이 완료되지 않았으므로 Top 결과를 표시하지 않습니다. "
                "메뉴 2번 일봉 갱신 완료 후 다시 조회하세요."
            )
        rows = build_market_result_rows(snapshot, screen_type)
        run = {
            "run_id": f"database:{screen_type}:{screen_date.isoformat()}",
            "as_of_date": screen_date.isoformat(),
            "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
            "source": "DATABASE",
            "data_source_mode": DATABASE_SOURCE_MODE,
            "market": market,
            "constituent_count": market_count,
            "matched_count": market_count,
            "positive_count": self._positive_count(rows, screen_type),
        }
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=latest_price_date,
            latest_indicator_date=screen_date,
        )

    def _membership(self, screen_type: str, screen_date: dt.date) -> IndexMembership:
        cache_key = (screen_type, screen_date)
        membership = self._index_membership_cache.get(cache_key)
        if membership is None:
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                membership = self.index_membership_fetcher(screen_type, screen_date)
            if membership.screen_type != screen_type:
                raise ValueError("Index membership does not match the requested screen")
            self._index_membership_cache[cache_key] = membership
        return membership

    @staticmethod
    def _index_market(screen_type: str) -> str:
        membership_types = INDEX_MEMBERSHIP_TYPES.get(
            screen_type,
            (screen_type,),
        )
        markets = tuple(
            dict.fromkeys(
                INDEX_GAINER_DEFINITIONS[value].market for value in membership_types
            )
        )
        return "+".join(markets)

    @staticmethod
    def _positive_count(rows: DataFrame, screen_type: str) -> int:
        metric = (
            "distance_from_52w_high_pct"
            if screen_type == "near_high_52w"
            else "weekly_return_pct"
            if screen_type in (INDEX_WEEKLY_SCREEN_TYPES | MARKET_WEEKLY_GAINER_SCREEN_TYPES)
            else (
                "weekly_trading_value_eok"
                if screen_type in WEEKLY_TRADING_VALUE_SCREEN_TYPES
                else "estimated_trading_value"
                if screen_type in MARKET_TRADING_VALUE_SCREEN_TYPES
                else "daily_return_pct"
            )
        )
        values = pd.to_numeric(rows.get(metric), errors="coerce")
        return int(values.gt(0).sum())

    def _membership_for_screen(
        self,
        screen_type: str,
        screen_date: dt.date,
        snapshot: DataFrame,
    ) -> IndexMembership:
        membership_types = INDEX_MEMBERSHIP_TYPES.get(
            screen_type,
            (screen_type,),
        )
        memberships: list[IndexMembership] = []
        for membership_type in membership_types:
            try:
                membership = self._membership(membership_type, screen_date)
            except Exception as error:
                raise ValueError(
                    f"{INDEX_GAINER_DEFINITIONS[membership_type].display_name} "
                    f"정확한 구성종목 조회 실패: {error}"
                ) from error
            memberships.append(membership)
        if len(memberships) == 1 and memberships[0].screen_type == screen_type:
            return memberships[0]
        return IndexMembership(
            screen_type=screen_type,
            index_code="+".join(item.index_code for item in memberships),
            index_name="+".join(item.index_name for item in memberships),
            as_of_date=min(item.as_of_date for item in memberships),
            tickers=tuple(
                sorted({ticker for item in memberships for ticker in item.tickers})
            ),
            source=" + ".join(item.source for item in memberships),
        )

    @staticmethod
    def _market_cap_proxy_membership(
        screen_type: str,
        screen_date: dt.date,
        snapshot: DataFrame,
    ) -> IndexMembership:
        """Last-resort, explicitly labelled proxy when public index APIs are unavailable."""

        definition = INDEX_GAINER_DEFINITIONS[screen_type]
        required = {"ticker", "market", "market_cap"}
        if missing := required.difference(snapshot.columns):
            raise ValueError(f"DB 지수 대체자료 필수 열이 없습니다: {sorted(missing)}")
        frame = exclude_spac_securities(snapshot).copy()
        frame["market"] = frame["market"].astype("string").str.upper().str.strip()
        frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
        frame = frame.loc[
            frame["market"].eq(definition.market) & frame["market_cap"].gt(0)
        ].sort_values(["market_cap", "ticker"], ascending=[False, True])
        minimum = max(30, int(definition.expected_count * 0.75))
        if len(frame) < minimum:
            raise ValueError(
                f"{definition.display_name} 공개 구성종목과 DB 시가총액 대체자료를 모두 "
                "확보하지 못했습니다."
            )
        tickers = tuple(frame.head(definition.expected_count)["ticker"].astype(str).str.zfill(6))
        return IndexMembership(
            screen_type=screen_type,
            index_code=definition.known_pykrx_code,
            index_name=f"{definition.display_name} (DB 시총 상위 대체)",
            as_of_date=screen_date,
            tickers=tickers,
            source="DATABASE:MARKET_CAP_PROXY",
        )

    def _load_investor_flow_screen(
        self, screen_type: str, *, as_of_date: object | None,
    ) -> ScreenDataset:
        if self._on_demand is None:
            raise ValueError("수급 거래대금 조회에는 PostgreSQL 수급 원천자료가 필요합니다.")
        with BaseDataRepository(self._on_demand.settings) as repository:
            latest_price = repository.latest_ohlcv_date()
            if latest_price is None:
                raise ValueError("DB에 일봉 자료가 없습니다.")
            selected = pd.Timestamp(as_of_date).date() if as_of_date is not None else latest_price
            if selected > latest_price:
                raise DatabaseDateMismatchError(
                    f"선택일 {selected}은 DB 마지막 일봉 {latest_price}보다 늦습니다."
                )
            flow = repository.get_market_investor_flow(selected)
            if flow.empty:
                raise ValueError(
                    f"{selected} 수급 자료가 DB에 없습니다. 수급 갱신을 먼저 실행하십시오."
                )
            master = repository.get_security_master_frame()
            prices = repository.get_market_ohlcv(selected, selected)
        if prices.empty:
            raise DatabaseDateMismatchError(f"{selected} 일봉이 DB에 없습니다.")
        rows = build_investor_flow_rows(flow, master, prices, screen_type)
        market, investor, direction = INVESTOR_FLOW_SCREEN_DEFINITIONS[screen_type]
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type] + (" (LS 원본 금액 검증)" if str(flow.attrs.get('source', '')).startswith('LS:T1702') else ""),
            run={
                "run_id": f"investor:{screen_type}:{selected}",
                "as_of_date": selected.isoformat(),
                "source": "LS_T1702_VERIFIED" if str(flow.attrs.get('source', '')).startswith('LS:T1702') else "POSTGRESQL_INVESTOR_FACTS",
                "data_source_mode": DATABASE_SOURCE_MODE,
                "market": market,
                "investor": investor,
                "direction": direction,
                "matched_count": len(rows),
            },
            rows=rows,
            latest_price_date=latest_price,
            latest_indicator_date=selected,
        )

    def _load_index_gainer_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
    ) -> ScreenDataset:
        snapshot, screen_date, latest_price_date = self._database_snapshot(as_of_date)
        membership = self._membership_for_screen(
            screen_type,
            screen_date,
            snapshot,
        )
        eligible_snapshot = exclude_spac_securities(snapshot)
        rows = (
            build_index_weekly_gainer_rows(eligible_snapshot, membership)
            if screen_type in INDEX_WEEKLY_SCREEN_TYPES
            else build_index_gainer_rows(
                eligible_snapshot,
                membership,
                limit=50 if screen_type == "kospi200_kosdaq150_daily_gainers" else 30,
            )
        )
        if rows.empty:
            raise ValueError(
                f"{membership.index_name} 구성종목과 {screen_date.isoformat()} "
                "기술지표 자료의 교집합이 없습니다."
            )

        generated_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
        run = {
            "run_id": f"database:{screen_type}:{screen_date.isoformat()}",
            "as_of_date": screen_date.isoformat(),
            "generated_at": generated_at,
            "source": "DATABASE",
            "data_source_mode": DATABASE_SOURCE_MODE,
            "membership_source": membership.source,
            "index_code": membership.index_code,
            "index_name": membership.index_name,
            "constituent_as_of_date": membership.as_of_date.isoformat(),
            "market": self._index_market(screen_type),
            "constituent_count": len(membership.tickers),
            "matched_count": int(
                eligible_snapshot["ticker"].astype(str).isin(membership.tickers).sum()
            ),
            "positive_count": self._positive_count(rows, screen_type),
        }
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=latest_price_date,
            latest_indicator_date=screen_date,
        )

    def _realtime_base(
        self,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> tuple[RealtimeQuoteSnapshot, DataFrame, dt.date]:
        quote_venue = str(quote_venue).strip().upper()
        if quote_venue not in QUOTE_VENUES:
            raise ValueError(f"Unsupported quote venue: {quote_venue!r}")
        cache_key = (
            f"{quote_venue}:latest"
            if as_of_date is None
            else f"{quote_venue}:{pd.Timestamp(as_of_date).date().isoformat()}"
        )
        now = time.monotonic()
        with self._realtime_cache_lock:
            cached = self._realtime_cache
            if (
                cached is not None
                and cached[0] == cache_key
                and now - cached[1] <= self.realtime_cache_seconds
            ):
                return cached[2], cached[3].copy(), cached[4]

            # Live quotes may already be on today's KST date while the DB
            # necessarily ends at the previous completed trading day.  Load
            # the latest complete DB snapshot as the indicator/reference
            # basis, then overlay the requested live quote date.
            database_snapshot, indicator_date, _ = (
                self._database_snapshot(None)
                if quote_venue == QUOTE_VENUE_KRX
                else self._database_snapshot(None, quote_venue)
            )

            universe_columns = ["ticker", "name", "market", "trade_date"]
            quotes = self.realtime_quote_fetcher(
                as_of_date,
                universe=database_snapshot[universe_columns].copy(),
                venue=quote_venue,
            )
            if quotes.as_of_date < indicator_date:
                database_snapshot, indicator_date, _ = (
                    self._database_snapshot(quotes.as_of_date)
                    if quote_venue == QUOTE_VENUE_KRX
                    else self._database_snapshot(quotes.as_of_date, quote_venue)
                )
            combined = overlay_realtime_quotes(database_snapshot, quotes)
            self._realtime_cache = (
                cache_key,
                time.monotonic(),
                quotes,
                combined.copy(),
                indicator_date,
            )
            return quotes, combined, indicator_date

    def _load_realtime_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> ScreenDataset:
        quotes, snapshot, indicator_date = self._realtime_base(
            as_of_date,
            quote_venue,
        )
        membership: IndexMembership | None = None
        if screen_type in MARKET_RESULT_SCREEN_TYPES:
            rows = build_market_result_rows(snapshot, screen_type)
            market = MARKET_RESULT_DEFINITIONS[screen_type]
            markets = _market_values(screen_type)
            constituent_count = int(
                exclude_spac_securities(snapshot)["market"]
                .astype("string")
                .str.upper()
                .str.strip()
                .isin(markets)
                .sum()
            )
            matched_count = constituent_count
        elif screen_type in INDEX_RELATED_SCREEN_TYPES:
            membership = self._membership_for_screen(
                screen_type,
                quotes.as_of_date,
                snapshot,
            )
            rows = (
                build_index_weekly_gainer_rows(snapshot, membership)
                if screen_type in INDEX_WEEKLY_SCREEN_TYPES
                else build_index_gainer_rows(
                    snapshot,
                    membership,
                    limit=max(1, len(snapshot)),
                )
            )
            market = self._index_market(screen_type)
            constituent_count = len(membership.tickers)
            matched_count = int(
                snapshot["ticker"].astype(str).isin(membership.tickers).sum()
            )
        elif screen_type == "near_high_52w":
            rows = exclude_spac_securities(snapshot).copy()
            rows["high_52w"] = pd.to_numeric(rows["high_52w"], errors="coerce")
            rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
            rows = rows.loc[rows["high_52w"].gt(0) & rows["close"].gt(0)].copy()
            rows["distance_from_52w_high_pct"] = (
                rows["close"].div(rows["high_52w"]).sub(1).mul(100)
            ).round(6)
            rows = rows.sort_values(
                ["distance_from_52w_high_pct", "ticker"],
                ascending=[False, True], kind="mergesort",
            ).reset_index(drop=True)
            rows.insert(0, "screen_type", screen_type)
            rows.insert(0, "rank", np.arange(1, len(rows) + 1))
            market = "ALL"
            constituent_count = len(snapshot)
            matched_count = len(snapshot)
        else:
            result = build_market_screens(
                snapshot,
                as_of_date=quotes.as_of_date,
                comparison_ticker=None,
                top_n=50,
            )
            rows = result.frames()[screen_type]
            market = "ALL"
            constituent_count = result.universe_count
            matched_count = len(snapshot)

        run = {
            "run_id": f"realtime:{screen_type}:{quotes.as_of_date.isoformat()}",
            "as_of_date": quotes.as_of_date.isoformat(),
            "generated_at": quotes.retrieved_at.isoformat(timespec="seconds"),
            "retrieved_at": quotes.retrieved_at.isoformat(timespec="seconds"),
            "source": quotes.source,
            "data_source_mode": REALTIME_SOURCE_MODE,
            "quote_venue": quote_venue,
            "market": market,
            "constituent_count": constituent_count,
            "matched_count": matched_count,
            "quote_count": len(quotes.rows),
            "indicator_basis_date": indicator_date.isoformat(),
            "adjusted_reference_count": int(
                snapshot["reference_price_adjustment_factor"].ne(1.0).sum()
            ),
            "positive_count": self._positive_count(rows, screen_type),
        }
        if membership is not None:
            run.update(
                {
                    "membership_source": membership.source,
                    "index_code": membership.index_code,
                    "index_name": membership.index_name,
                    "constituent_as_of_date": membership.as_of_date.isoformat(),
                }
            )
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=quotes.as_of_date,
            latest_indicator_date=indicator_date,
        )

    def resolve_ticker(self, ticker_or_name: object) -> str:
        """Resolve a six-digit ticker or an exact security name from local metadata."""

        if self._on_demand is not None:
            return self._on_demand.resolve_ticker(ticker_or_name)

        query = str(ticker_or_name).strip()
        if not query:
            raise ValueError("종목명 또는 6자리 종목코드를 입력하세요.")
        if query.isdigit():
            return normalize_ticker(query)
        with open_research_store(self.database_target, read_only=True) as store:
            matches = store.find_securities_by_name(query)
        if not matches:
            raise ValueError(f"종목명 '{query}'을 종목 마스터에서 찾을 수 없습니다.")
        if len(matches) > 1:
            tickers = ", ".join(str(row["ticker"]) for row in matches)
            raise ValueError(f"종목명 '{query}'이 여러 종목과 일치합니다: {tickers}")
        return normalize_ticker(matches[0]["ticker"])

    def search_securities(self, query: object, *, limit: int = 20) -> list[dict[str, str]]:
        """Search PostgreSQL security master by code/name for the Qt stock finder."""
        text = str(query).strip()
        if not text:
            return []
        if self._on_demand is None:
            raise RuntimeError("종목 검색에는 PostgreSQL 원천자료가 필요합니다.")
        with BaseDataRepository(self._on_demand.settings) as repository:
            master = repository.get_security_master_frame()
        if master.empty:
            return []
        code_col = "stock_code" if "stock_code" in master.columns else "ticker"
        name_col = "stock_name" if "stock_name" in master.columns else "name"
        market_col = "market" if "market" in master.columns else None
        codes = master[code_col].astype(str).str.zfill(6)
        names = master[name_col].fillna("").astype(str)
        mask = codes.str.contains(text, case=False, regex=False) | names.str.contains(text, case=False, regex=False)
        matches = master.loc[mask].copy().head(max(1, int(limit)))
        rows: list[dict[str, str]] = []
        for _, row in matches.iterrows():
            rows.append({
                "ticker": str(row.get(code_col, "")).zfill(6),
                "name": str(row.get(name_col, "")),
                "market": str(row.get(market_col, "")) if market_col else "",
            })
        return rows

    def clear_realtime_cache(self) -> None:
        """Discard live rows so database-only charts never inherit them."""

        with self._realtime_cache_lock:
            self._realtime_cache = None

    def _cached_realtime_chart_bar(self, ticker: str) -> dict[str, object] | None:
        with self._realtime_cache_lock:
            cached = self._realtime_cache
            if cached is None:
                return None
            rows = cached[3]
            matched = rows.loc[rows["ticker"].astype(str).eq(ticker)]
            if matched.empty:
                return None
            return matched.iloc[-1].to_dict()

    def load_chart(
        self,
        ticker: object,
        *,
        timeframes: tuple[str, ...] = ("D", "W"),
        include_investor: bool = False,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
    ) -> ChartDataset:
        code = self.resolve_ticker(ticker)
        live_bar = self._cached_realtime_chart_bar(code) if quote_venue == QUOTE_VENUE_KRX else None
        if self._on_demand is not None:
            result = self._on_demand.load_chart(
                code,
                timeframes=timeframes,
                include_investor=include_investor,
                live_bar=live_bar,
                venue=quote_venue,
                cancel_event=cancel_event,
            )
            return ChartDataset(
                ticker=result.ticker,
                name=result.name,
                market=result.market,
                industry=result.industry,
                daily=result.bars.get("D", DataFrame()),
                weekly=result.bars.get("W", DataFrame()),
                monthly=result.bars.get("M", DataFrame()),
                quarterly=result.bars.get("Q", DataFrame()),
                yearly=result.bars.get("Y", DataFrame()),
                investor=result.investor,
                loaded_timeframes=frozenset(result.bars),
                investor_loaded=include_investor,
            )
        with open_research_store(self.database_target, read_only=True) as store:
            history = store.get_adjusted_ohlcv(code)
            security = store.get_security(code) or {}
        if history.empty:
            raise ValueError(f"{code}의 저장된 수정주가 일봉이 없습니다.")

        indicators = calculate_technical_indicators(history, ticker=code)
        daily = history[["open", "high", "low", "close", "volume"]].copy()
        daily = daily.join(indicators.daily.drop(columns=["close"]))
        daily["previous_volume"] = daily["volume"].shift(1)
        daily["volume_color"] = np.select(
            [
                daily["volume"] > daily["previous_volume"],
                daily["volume"] < daily["previous_volume"],
            ],
            ["#d62728", "#1f77b4"],
            default="#808080",
        )
        ema_fast = daily["close"].ewm(span=12, adjust=False, min_periods=12).mean()
        ema_slow = daily["close"].ewm(span=26, adjust=False, min_periods=26).mean()
        daily["macd"] = ema_fast - ema_slow
        daily["macd_signal"] = (
            daily["macd"]
            .ewm(
                span=9,
                adjust=False,
                min_periods=9,
            )
            .mean()
        )
        daily["macd_oscillator"] = daily["macd"] - daily["macd_signal"]

        bollinger_period = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
        bollinger = daily["close"].rolling(bollinger_period, min_periods=bollinger_period)
        daily["bb_mid_20"] = daily["close"].ewm(
            span=bollinger_period, adjust=False, min_periods=bollinger_period
        ).mean()
        bollinger_deviation = bollinger.std(ddof=0)
        deviations = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.deviations
        daily["bb_upper_20_2"] = daily["bb_mid_20"] + deviations * bollinger_deviation
        daily["bb_lower_20_2"] = daily["bb_mid_20"] - deviations * bollinger_deviation

        change = daily["close"].diff()
        average_gain = (
            change.clip(lower=0)
            .ewm(
                span=RSI_PERIOD,
                adjust=False,
                min_periods=RSI_PERIOD,
            )
            .mean()
        )
        average_loss = (
            (-change.clip(upper=0))
            .ewm(
                span=RSI_PERIOD,
                adjust=False,
                min_periods=RSI_PERIOD,
            )
            .mean()
        )
        relative_strength = average_gain / average_loss.replace(0, np.nan)
        daily["rsi_14"] = 100.0 - 100.0 / (1.0 + relative_strength)
        daily.loc[average_loss.eq(0) & average_gain.gt(0), "rsi_14"] = 100.0
        daily.loc[average_loss.eq(0) & average_gain.eq(0), "rsi_14"] = 50.0
        daily["rsi_signal_9"] = (
            daily["rsi_14"]
            .ewm(span=RSI_SIGNAL_PERIOD, adjust=False, min_periods=RSI_SIGNAL_PERIOD)
            .mean()
        )

        lowest_low = (
            daily["low"]
            .rolling(
                STOCHASTIC_K_PERIOD,
                min_periods=STOCHASTIC_K_PERIOD,
            )
            .min()
        )
        highest_high = (
            daily["high"]
            .rolling(
                STOCHASTIC_K_PERIOD,
                min_periods=STOCHASTIC_K_PERIOD,
            )
            .max()
        )
        price_range = (highest_high - lowest_low).replace(0, np.nan)
        fast_k = (daily["close"] - lowest_low) / price_range * 100.0
        daily["stoch_slow_k"] = fast_k.ewm(
            span=STOCHASTIC_K_SMOOTHING, adjust=False,
            min_periods=STOCHASTIC_K_SMOOTHING,
        ).mean()
        daily["stoch_slow_d"] = (
            daily["stoch_slow_k"]
            .ewm(span=STOCHASTIC_D_PERIOD, adjust=False, min_periods=STOCHASTIC_D_PERIOD)
            .mean()
        )

        weekly = indicators.weekly.copy()
        for window in EMA_WINDOWS:
            weekly[f"ema_{window}"] = (
                weekly["close"]
                .ewm(
                    span=window,
                    adjust=False,
                    min_periods=window,
                )
                .mean()
            )

        return ChartDataset(
            ticker=code,
            name=str(security.get("name") or code),
            market=str(security.get("market") or ""),
            industry=str(security.get("industry") or ""),
            daily=daily,
            weekly=weekly,
            loaded_timeframes=frozenset({"D", "W"}),
            investor_loaded=True,
        )


def select_chart_window(
    dataset: ChartDataset,
    trading_days: int | None,
) -> tuple[DataFrame, DataFrame]:
    """Select daily rows and the weekly bars covering the same visible period."""

    if trading_days is not None and trading_days < 1:
        raise ValueError("거래일수는 1 이상이어야 합니다.")
    daily = dataset.daily if trading_days is None else dataset.daily.tail(trading_days)
    if daily.empty:
        raise ValueError(f"{dataset.ticker}의 표시 가능한 일봉이 없습니다.")
    if trading_days is None:
        return daily.copy(), dataset.weekly.copy()

    visible = daily.assign(
        trade_date=daily.index,
        week_end=daily.index.to_period("W-FRI").end_time.normalize(),
    )
    weekly = visible.groupby("week_end", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        trading_days=("close", "size"),
        last_trade_date=("trade_date", "max"),
    )
    weekly.index = pd.DatetimeIndex(weekly.index, name="week_end")
    weekly.insert(0, "ticker", dataset.ticker)
    derived_columns = [column for column in dataset.weekly.columns if column not in weekly.columns]
    weekly = weekly.join(dataset.weekly[derived_columns], how="left")
    return daily.copy(), weekly.copy()


def calculate_volume_profile(
    frame: DataFrame,
    *,
    bins: int = 15,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Distribute selected-period volume across each candle's traded price range."""

    if bins < 1:
        raise ValueError("bins must be at least 1")
    if frame.empty:
        return np.array([]), np.array([]), 0.0
    lower = float(frame["low"].min())
    upper = float(frame["high"].max())
    if not np.isfinite(lower) or not np.isfinite(upper):
        raise ValueError("가격 범위에 유효하지 않은 값이 있습니다.")
    if upper <= lower:
        upper = lower + max(abs(lower) * 0.01, 1.0)
    edges = np.linspace(lower, upper, bins + 1)
    lows = frame["low"].to_numpy(dtype="float64")
    highs = frame["high"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    candle_volume = frame["volume"].to_numpy(dtype="float64")
    if not np.isfinite(candle_volume).all() or (candle_volume < 0).any():
        raise ValueError("거래량에 유효하지 않은 값이 있습니다.")

    overlap = np.minimum(highs[:, None], edges[None, 1:]) - np.maximum(
        lows[:, None],
        edges[None, :-1],
    )
    overlap = np.clip(overlap, 0.0, None)
    overlap_total = overlap.sum(axis=1)
    weights = np.divide(
        overlap,
        overlap_total[:, None],
        out=np.zeros_like(overlap),
        where=overlap_total[:, None] > 0,
    )
    volume = (weights * candle_volume[:, None]).sum(axis=0)

    point_rows = overlap_total <= 0
    if point_rows.any():
        point_buckets = np.clip(
            np.digitize(closes[point_rows], edges) - 1,
            0,
            bins - 1,
        )
        np.add.at(volume, point_buckets, candle_volume[point_rows])
    centers = (edges[:-1] + edges[1:]) / 2.0
    return centers, volume, float(edges[1] - edges[0]) * 0.84
