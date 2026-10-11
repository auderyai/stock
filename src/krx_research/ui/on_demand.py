"""PostgreSQL base-data readers used by the workstation GUI.

No candle, indicator, investor total, or screen result produced here is written
back to PostgreSQL.  The database remains a fact store and this module performs
the requested representation in memory.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics.ema_similarity import (
    EMA_DEFAULT_GAP_TOLERANCE,
    EMA_DEFAULT_MIN_SIMILARITY,
    calculate_ema_similarity_metrics,
)
from krx_research.analytics.technical_indicators import FORMULA_VERSION
from krx_research.data_engine.config import DataEngineSettings, settings_from_database_target
from krx_research.data_engine.indicators import calculate_indicators
from krx_research.data_engine.investor import (
    aggregate_investor_flow,
    normalize_investor_code,
)
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.data_engine.timeframes import resample_ohlcv
from krx_research.database.settings import PostgreSQLSettings


EMA_WINDOWS = (5, 10, 15, 33, 56, 112, 224, 448)
SCREEN_CACHE_SECONDS = 300
DATABASE_VENUES = frozenset({"KRX", "NXT", "COMBINED"})
CHART_CACHE_SECONDS = 300
CHART_CACHE_MAX_TICKERS = 16
PRICE_ADJUSTMENT_RATIO_TOLERANCE = 0.02
NAVER_INVESTOR_TREND_URL = (
    "https://m.stock.naver.com/front-api/stock/domestic/trend"
)
NAVER_INVESTOR_TREND_COUNT = 800
NAVER_INVESTOR_PAGE_SIZE = 100
NAVER_INVESTOR_MAX_RESPONSE_BYTES = 2_000_000
NAVER_INVESTOR_CACHE_SECONDS = 6 * 60 * 60
NAVER_INVESTOR_TIMEOUT_SECONDS = 20.0
NAVER_INVESTOR_RETRIES = 2
SPAC_PATTERN = re.compile(
    r"(?:스\s*팩|기업인수목적|(?<![A-Za-z])SPAC(?![A-Za-z]))",
    flags=re.IGNORECASE,
)
TIMEFRAME_LABELS = {
    "D": "일봉",
    "W": "주봉",
    "M": "월봉",
    "Q": "분기봉",
    "Y": "년봉",
}
SCREEN_LOOKBACK_DAYS = {
    "ema_similarity": 2400,
    "high_52w": 520,
    "near_high_52w": 520,
    "bollinger_breakout": 300,
    "weekly_return": 45,
    "kospi_weekly_gainers": 45,
    "kosdaq_weekly_gainers": 45,
    "kospi200_daily_gainers": 45,
    "kosdaq150_daily_gainers": 45,
    "kospi200_kosdaq150_daily_gainers": 45,
    "kospi_daily_gainers": 45,
    "kosdaq_daily_gainers": 45,
    "kospi_kosdaq_daily_gainers": 45,
    "kospi_kosdaq_daily_trading_value": 45,
    "kospi_weekly_trading_value": 14,
    "kosdaq_weekly_trading_value": 14,
    "kospi_kosdaq_weekly_trading_value": 14,
    "kospi200_weekly_gainers": 45,
    "kosdaq150_weekly_gainers": 45,
    "kospi200_kosdaq150_weekly_gainers": 45,
}


@dataclass(frozen=True)
class OnDemandScreenResult:
    rows: DataFrame
    as_of_date: dt.date
    universe_count: int


@dataclass(frozen=True)
class OnDemandChartResult:
    ticker: str
    name: str
    market: str
    industry: str
    bars: dict[str, DataFrame]
    investor: dict[str, DataFrame]


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError()


def _empty_screen_frame() -> DataFrame:
    return DataFrame(
        columns=[
            "rank",
            "screen_type",
            "ticker",
            "name",
            "market",
            "industry",
            "market_cap",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "estimated_trading_value",
            "daily_return_pct",
            "weekly_return_pct",
        ]
    )


def _prepare_history(raw: DataFrame, master: DataFrame) -> tuple[DataFrame, dt.date]:
    if raw.empty:
        raise ValueError("선택한 기준일까지 PostgreSQL 일봉 원천자료가 없습니다.")
    history = raw.rename(
        columns={
            "stock_code": "ticker",
            "open_price": "open",
            "high_price": "high",
            "low_price": "low",
            "close_price": "close",
        }
    ).copy()
    history["ticker"] = history["ticker"].astype(str).str.zfill(6)
    history["trade_date"] = pd.to_datetime(history["trade_date"], errors="coerce")
    number_columns = ["open", "high", "low", "close", "volume", "amount"]
    if "change_rate" in history:
        number_columns.append("change_rate")
    for column in number_columns:
        history[column] = pd.to_numeric(history[column], errors="coerce")
    history = history.dropna(subset=["ticker", "trade_date", "open", "high", "low", "close"])
    history["volume"] = history["volume"].fillna(0)
    history = history.sort_values(["ticker", "trade_date"], ignore_index=True)
    history = history.drop_duplicates(["ticker", "trade_date"], keep="last")
    # Keep the persisted OHLCV price basis available for high screens.  The
    # inferred corporate-action adjustment below can otherwise erase a genuine
    # prior high when a vendor's daily change rate is inconsistent with prices.
    history["source_high"] = history["high"]
    history = _back_adjust_corporate_actions(history)
    actual_date = history["trade_date"].max().date()
    history = history.loc[history["trade_date"].dt.date <= actual_date].copy()

    dimension = master.rename(
        columns={"stock_code": "ticker", "stock_name": "name"}
    ).copy()
    if dimension.empty:
        dimension = DataFrame(
            columns=["ticker", "name", "market", "industry", "market_cap"]
        )
    dimension["ticker"] = dimension["ticker"].astype(str).str.zfill(6)
    for column in ("name", "market", "industry", "market_cap"):
        if column not in dimension:
            dimension[column] = np.nan if column == "market_cap" else ""
    history = history.merge(
        dimension[["ticker", "name", "market", "industry", "market_cap"]],
        on="ticker",
        how="left",
        validate="m:1",
    )
    history["name"] = history["name"].fillna(history["ticker"])
    history["market"] = history["market"].fillna("").astype(str).str.upper().str.strip()
    history["industry"] = history["industry"].fillna("")
    history = history.loc[
        ~history["name"].astype(str).str.contains(SPAC_PATTERN, na=False)
    ].copy()
    if history.empty:
        raise ValueError("스팩 제외 후 스크리닝할 종목이 없습니다.")
    return history, actual_date


def _back_adjust_corporate_actions(history: DataFrame) -> DataFrame:
    """Put prior OHLC prices on the latest capital-action price basis.

    KRX ``change_rate`` is calculated from the exchange comparison price and
    therefore remains meaningful on split, consolidation, and capital-change
    dates.  A large mismatch between that official return and the raw
    close-to-close ratio identifies the adjustment ratio without persisting a
    second price table.
    """

    result = history.copy()
    result["price_adjustment_factor"] = 1.0
    if result.empty or "change_rate" not in result:
        return result
    previous_close = result.groupby(
        "ticker", sort=False, observed=True
    )["close"].shift(1)
    official_return = pd.to_numeric(result["change_rate"], errors="coerce")
    denominator = 1.0 + official_return.div(100.0)
    implied_previous_close = result["close"].div(
        denominator.where(denominator.gt(0))
    )
    event_ratio = implied_previous_close.div(previous_close.replace(0, np.nan))
    valid_event = (
        event_ratio.notna()
        & np.isfinite(event_ratio)
        & event_ratio.gt(0)
        & event_ratio.sub(1.0).abs().ge(PRICE_ADJUSTMENT_RATIO_TOLERANCE)
    )
    event_factor = event_ratio.where(valid_event, 1.0)

    def cumulative_prior_factor(values: pd.Series) -> pd.Series:
        applies_to_prior_row = values.shift(-1, fill_value=1.0)
        return applies_to_prior_row.iloc[::-1].cumprod().iloc[::-1]

    adjustment = event_factor.groupby(
        result["ticker"], sort=False, observed=True
    ).transform(cumulative_prior_factor)
    result["price_adjustment_factor"] = adjustment
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="coerce").mul(adjustment)
    return result


def _add_daily_metrics(history: DataFrame) -> DataFrame:
    result = history.copy()
    grouped = result.groupby("ticker", sort=False, observed=True)
    result["observations"] = grouped.cumcount() + 1
    result["previous_close"] = grouped["close"].shift(1)
    calculated_return = (
        result["close"].div(result["previous_close"].replace(0, np.nan)).sub(1).mul(100)
    )
    if "change_rate" in result:
        official_return = pd.to_numeric(result["change_rate"], errors="coerce")
        result["daily_return_pct"] = official_return.where(
            official_return.notna(), calculated_return
        )
    else:
        result["daily_return_pct"] = calculated_return
    amount = pd.to_numeric(result.get("amount"), errors="coerce")
    estimated = result["close"] * result["volume"]
    result["estimated_trading_value"] = amount.where(amount.gt(0), estimated)
    return result


def _weekly_metrics(history: DataFrame) -> DataFrame:
    working = history.assign(
        _period=history["trade_date"].dt.to_period("W-FRI")
    )
    weekly = (
        working.groupby(["ticker", "_period"], sort=True, observed=True)
        .agg(
            trade_date=("trade_date", "max"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            name=("name", "last"),
            market=("market", "last"),
            industry=("industry", "last"),
        )
        .reset_index(drop=False)
    )
    grouped = weekly.groupby("ticker", sort=False, observed=True)
    weekly["weekly_previous_close"] = grouped["close"].shift(1)
    weekly["weekly_return_pct"] = (
        weekly["close"]
        .div(weekly["weekly_previous_close"].replace(0, np.nan))
        .sub(1)
        .mul(100)
    )
    weekly["bb_mid_20"] = grouped["close"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    deviation = grouped["close"].transform(
        lambda values: values.rolling(20, min_periods=20).std(ddof=0)
    )
    weekly["bb_upper_20_2"] = weekly["bb_mid_20"] + 2.0 * deviation
    weekly["is_bb_upper_breakout"] = (
        weekly["bb_upper_20_2"].notna()
        & weekly["close"].gt(weekly["bb_upper_20_2"])
    )
    return weekly


def _latest_with_weekly(history: DataFrame) -> DataFrame:
    daily = _add_daily_metrics(history)
    latest = daily.groupby("ticker", sort=False, observed=True).tail(1).copy()
    as_of_timestamp = daily["trade_date"].max()
    latest = latest.loc[latest["trade_date"].eq(as_of_timestamp)].copy()
    weekly = _weekly_metrics(history)
    weekly_latest = weekly.groupby("ticker", sort=False, observed=True).tail(1)
    weekly_latest = weekly_latest[
        [
            "ticker",
            "weekly_previous_close",
            "weekly_return_pct",
            "bb_upper_20_2",
            "is_bb_upper_breakout",
        ]
    ]
    return latest.merge(weekly_latest, on="ticker", how="left", validate="1:1")


def _prior_52w_high(history: DataFrame, *, column: str = "high") -> pd.Series:
    """Use up to 252 prior sessions; newly listed stocks use available history."""

    return history.groupby("ticker", sort=False, observed=True)[column].transform(
        lambda values: values.shift(1).rolling(252, min_periods=1).max()
    )


def _rank(
    frame: DataFrame,
    screen_type: str,
    *,
    by: list[str],
    ascending: list[bool],
    limit: int,
) -> DataFrame:
    if frame.empty:
        return _empty_screen_frame()
    result = frame.sort_values(
        by,
        ascending=ascending,
        na_position="last",
        kind="mergesort",
    ).head(limit).copy()
    result.insert(0, "screen_type", screen_type)
    result.insert(0, "rank", np.arange(1, len(result) + 1, dtype="int64"))
    return result.reset_index(drop=True)


def calculate_screen(
    history: DataFrame,
    screen_type: str,
    *,
    comparison_ticker: str = "222800",
) -> DataFrame:
    """Calculate one GUI screen directly from a bounded raw daily window."""

    latest = _latest_with_weekly(history)
    if screen_type in {"kospi_weekly_trading_value", "kosdaq_weekly_trading_value", "kospi_kosdaq_weekly_trading_value"}:
        market_map = {
            "kospi_weekly_trading_value": ("KOSPI",),
            "kosdaq_weekly_trading_value": ("KOSDAQ",),
            "kospi_kosdaq_weekly_trading_value": ("KOSPI", "KOSDAQ"),
        }
        as_of = history["trade_date"].max()
        week_start = as_of - pd.Timedelta(days=int(as_of.weekday()))
        weekly = history.loc[history["trade_date"].between(week_start, as_of)].copy()
        weekly["amount"] = pd.to_numeric(weekly["amount"], errors="coerce").fillna(0)
        totals = weekly.groupby("ticker", as_index=False, observed=True)["amount"].sum().rename(columns={"amount": "weekly_trading_value"})
        selected = latest.merge(totals, on="ticker", how="left", validate="1:1")
        selected["weekly_trading_value_eok"] = selected["weekly_trading_value"].div(100_000_000.0)
        selected = selected.loc[selected["market"].isin(market_map[screen_type]) & selected["weekly_trading_value_eok"].notna()].copy()
        return selected.reset_index(drop=True)
    if screen_type == "high_52w":
        daily = _add_daily_metrics(history)
        daily["prior_high_52w"] = _prior_52w_high(daily)
        # LS venue history can contain unadjusted splits and vendor glitches.
        # Until its price basis is verified, a >35% close gap invalidates a
        # 52-week comparison for this bar and the following 252 sessions.
        previous_close = daily.groupby("ticker", sort=False)["close"].shift(1)
        gap = daily["close"].div(previous_close.where(previous_close.gt(0)))
        discontinuity = gap.gt(1.35) | gap.lt(0.65)
        daily["uncertain_52w_basis"] = discontinuity.groupby(
            daily["ticker"], sort=False
        ).transform(lambda values: values.rolling(253, min_periods=1).max().astype(bool))
        if "source_high" in daily:
            daily["prior_source_high_52w"] = _prior_52w_high(daily, column="source_high")
        selected = daily.groupby("ticker", sort=False, observed=True).tail(1)
        as_of_timestamp = daily["trade_date"].max()
        selected = selected.loc[selected["trade_date"].eq(as_of_timestamp)].copy()
        weekly_columns = latest[
            ["ticker", "weekly_return_pct", "bb_upper_20_2"]
        ]
        selected = selected.merge(weekly_columns, on="ticker", how="left", validate="1:1")
        if "prior_source_high_52w" in selected:
            selected["prior_high_52w"] = selected[
                ["prior_high_52w", "prior_source_high_52w"]
            ].max(axis=1)
        selected = selected.loc[
            selected["prior_high_52w"].notna()
            & selected["high"].gt(selected["prior_high_52w"])
            & ~selected["uncertain_52w_basis"]
        ].copy()
        return _rank(
            selected,
            screen_type,
            by=["daily_return_pct", "estimated_trading_value", "ticker"],
            ascending=[False, False, True],
            limit=len(selected),
        )

    if screen_type == "near_high_52w":
        daily = _add_daily_metrics(history)
        grouped = daily.groupby("ticker", sort=False, observed=True)
        daily["high_52w"] = grouped["high"].transform(
            lambda values: values.rolling(252, min_periods=1).max()
        )
        if "source_high" in daily:
            source_high = grouped["source_high"].transform(
                lambda values: values.rolling(252, min_periods=1).max()
            )
            daily["high_52w"] = pd.concat(
                [daily["high_52w"], source_high], axis=1
            ).max(axis=1)
        selected = daily.groupby("ticker", sort=False, observed=True).tail(1).copy()
        selected = selected.loc[
            selected["trade_date"].eq(daily["trade_date"].max())
            & selected["high_52w"].gt(0)
            & selected["close"].gt(0)
        ].copy()
        selected = selected.merge(
            latest[["ticker", "weekly_return_pct"]],
            on="ticker", how="left", validate="1:1",
        )
        selected["distance_from_52w_high_pct"] = (
            selected["close"].div(selected["high_52w"]).sub(1).mul(100)
        ).round(6)
        return _rank(
            selected, screen_type,
            by=["distance_from_52w_high_pct", "ticker"],
            ascending=[False, True], limit=len(selected),
        )

    if screen_type == "bollinger_breakout":
        selected = latest.loc[latest["is_bb_upper_breakout"].fillna(False)].copy()
        return _rank(
            selected,
            screen_type,
            by=["weekly_return_pct", "estimated_trading_value", "ticker"],
            ascending=[False, False, True],
            limit=len(selected),
        )

    if screen_type in {"weekly_return", "kospi_weekly_gainers", "kosdaq_weekly_gainers"}:
        # Whole-market filtering/ranking is centralized in ui.data.build_market_result_rows
        # so DB and on-demand paths share one implementation.
        return latest.reset_index(drop=True)

    if screen_type == "ema_similarity":
        daily = _add_daily_metrics(history)
        grouped = daily.groupby("ticker", sort=False, observed=True)["close"]
        for window in EMA_WINDOWS:
            daily[f"ema_{window}"] = grouped.transform(
                lambda values, period=window: values.ewm(
                    span=period,
                    adjust=False,
                    min_periods=period,
                ).mean()
            )
        selected = daily.groupby("ticker", sort=False, observed=True).tail(1).copy()
        selected = selected.merge(
            latest[["ticker", "weekly_return_pct"]],
            on="ticker",
            how="left",
            validate="1:1",
        )
        profile_columns = ["close", *(f"ema_{window}" for window in EMA_WINDOWS)]
        valid = selected.loc[
            selected[profile_columns].notna().all(axis=1)
            & selected[profile_columns].gt(0).all(axis=1)
        ].copy()
        target_code = str(comparison_ticker).zfill(6)
        target = valid.loc[valid["ticker"].eq(target_code)]
        if target.empty:
            raise ValueError(
                f"기준 종목 {target_code}의 EMA 448 계산 자료가 부족합니다."
            )
        metrics = calculate_ema_similarity_metrics(
            valid,
            reference_index=target.index[0],
        )
        valid = valid.join(metrics)
        valid = valid.loc[
            ~valid["ticker"].eq(target_code)
            & valid["ema_order_similarity_pct"].ge(
                EMA_DEFAULT_MIN_SIMILARITY - 1e-12
            )
            & valid["ema_max_gap_difference_pct"].le(
                EMA_DEFAULT_GAP_TOLERANCE + 1e-12
            )
        ].copy()
        return _rank(
            valid,
            screen_type,
            by=[
                "ema_exact_array_match",
                "ema_order_similarity_pct",
                "ema_max_gap_difference_pct",
                "ema_shape_distance_pct",
                "name",
                "ticker",
            ],
            ascending=[False, False, True, True, True, True],
            limit=len(valid),
        )

    if screen_type in {
        "kospi200_daily_gainers",
        "kosdaq150_daily_gainers",
        "kospi200_kosdaq150_daily_gainers",
        "kospi_daily_gainers",
        "kosdaq_daily_gainers",
        "kospi_kosdaq_daily_gainers",
        "kospi_kosdaq_daily_trading_value",
    }:
        return latest.reset_index(drop=True)
    if screen_type in {
        "kospi200_weekly_gainers",
        "kosdaq150_weekly_gainers",
        "kospi200_kosdaq150_weekly_gainers",
    }:
        return latest.reset_index(drop=True)
    raise ValueError(f"지원하지 않는 스크리닝: {screen_type}")


def build_overlay_snapshot(history: DataFrame) -> DataFrame:
    """Build the complete compatibility snapshot needed for live quote overlay."""

    daily = _add_daily_metrics(history)
    grouped = daily.groupby("ticker", sort=False, observed=True)
    close_grouped = grouped["close"]
    ema_columns: list[str] = []
    for window in EMA_WINDOWS:
        column = f"ema_{window}"
        ema_columns.append(column)
        daily[column] = close_grouped.transform(
            lambda values, period=window: values.ewm(
                span=period,
                adjust=False,
                min_periods=period,
            ).mean()
        )
    daily["prior_high_52w"] = _prior_52w_high(daily)
    daily["high_52w"] = grouped["high"].transform(
        lambda values: values.rolling(252, min_periods=1).max()
    )
    if "source_high" in daily:
        daily["prior_source_high_52w"] = _prior_52w_high(daily, column="source_high")
        daily["source_high_52w"] = grouped["source_high"].transform(
            lambda values: values.rolling(252, min_periods=1).max()
        )
    daily["distance_from_52w_high_pct"] = (
        daily["close"].div(daily["high_52w"].replace(0, np.nan)).sub(1).mul(100)
    )
    daily["is_52w_high"] = (
        daily["high_52w"].notna() & daily["high"].ge(daily["high_52w"])
    ).astype("int64")
    daily["is_52w_breakout"] = (
        daily["prior_high_52w"].notna()
        & daily["high"].gt(daily["prior_high_52w"])
    ).astype("int64")
    ready = daily[ema_columns].notna().all(axis=1)
    bullish = ready.copy()
    bearish = ready.copy()
    for shorter, longer in zip(ema_columns, ema_columns[1:]):
        bullish &= daily[shorter].gt(daily[longer])
        bearish &= daily[shorter].lt(daily[longer])
    daily["ema_alignment"] = "insufficient"
    daily.loc[ready, "ema_alignment"] = "mixed"
    daily.loc[bullish, "ema_alignment"] = "bullish"
    daily.loc[bearish, "ema_alignment"] = "bearish"
    daily["close_above_ema5"] = daily["close"].gt(daily["ema_5"]).astype("int64")
    daily["history_ready_448"] = daily["observations"].ge(448).astype("int64")
    daily["formula_version"] = FORMULA_VERSION
    latest = daily.groupby("ticker", sort=False, observed=True).tail(1).copy()

    weekly = _weekly_metrics(history)
    weekly_latest = weekly.groupby("ticker", sort=False, observed=True).tail(1).copy()
    weekly_latest["week_end"] = weekly_latest["_period"].dt.end_time.dt.normalize()
    weekly_latest = weekly_latest.rename(
        columns={
            "trade_date": "weekly_last_trade_date",
            "high": "weekly_high",
            "close": "weekly_close",
        }
    )
    weekly_columns = [
        "ticker",
        "week_end",
        "weekly_last_trade_date",
        "weekly_previous_close",
        "weekly_high",
        "weekly_close",
        "weekly_return_pct",
        "bb_upper_20_2",
        "is_bb_upper_breakout",
    ]
    return latest.merge(
        weekly_latest[weekly_columns],
        on="ticker",
        how="left",
        validate="1:1",
    ).reset_index(drop=True)


def _chart_frame(raw: DataFrame, timeframe: str) -> DataFrame:
    bars = resample_ohlcv(raw, timeframe)
    calculated = calculate_indicators(bars, timeframe)
    frame = calculated.rename(
        columns={
            "open_price": "open",
            "high_price": "high",
            "low_price": "low",
            "close_price": "close",
            "bb_upper": "bb_upper_20_2",
            "bb_lower": "bb_lower_20_2",
            "macd_hist": "macd_oscillator",
        }
    ).copy()
    frame["previous_volume"] = frame["volume"].shift(1)
    frame["volume_color"] = np.select(
        [
            frame["volume"].gt(frame["previous_volume"]),
            frame["volume"].lt(frame["previous_volume"]),
        ],
        ["#d62728", "#1f77b4"],
        default="#808080",
    )
    return frame


def _append_live_chart_bar(
    raw: DataFrame,
    ticker: str,
    live_bar: dict[str, object] | None,
) -> tuple[DataFrame, bool]:
    """Return DB history with the cached live candle inserted or replaced."""

    if not live_bar:
        return raw, False
    trade_date = pd.to_datetime(live_bar.get("trade_date"), errors="coerce")
    if pd.isna(trade_date):
        return raw, False
    values = {
        "open_price": live_bar.get("open"),
        "high_price": live_bar.get("high"),
        "low_price": live_bar.get("low"),
        "close_price": live_bar.get("close"),
        "volume": live_bar.get("volume", 0),
        "amount": live_bar.get("estimated_trading_value", 0),
        "change_rate": live_bar.get("daily_return_pct"),
    }
    numeric = {
        key: pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        for key, value in values.items()
    }
    if any(pd.isna(numeric[key]) for key in ("open_price", "high_price", "low_price", "close_price")):
        return raw, False

    result = raw.copy(deep=True)
    if "trade_date" in result.columns:
        dates = pd.to_datetime(result["trade_date"], errors="coerce").dt.normalize()
        result = result.loc[dates.ne(trade_date.normalize())].copy()
    else:
        dates = pd.to_datetime(result.index, errors="coerce").normalize()
        result = result.loc[dates != trade_date.normalize()].copy()
        result = result.reset_index().rename(columns={result.index.name or "index": "trade_date"})
    row = {
        "stock_code": ticker,
        "trade_date": trade_date.normalize(),
        **numeric,
    }
    result = pd.concat([result, DataFrame([row])], ignore_index=True, sort=False)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result = result.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    return result, True


def _read_bounded_response(response: object, *, limit: int) -> bytes:
    opened = response
    enter = getattr(response, "__enter__", None)
    if callable(enter):
        opened = enter()
    try:
        reader = getattr(opened, "read", None)
        if not callable(reader):
            raise TypeError("Naver 응답 객체에 read()가 없습니다.")
        payload = reader(limit + 1)
    finally:
        exit_method = getattr(response, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)
        else:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    if len(payload) > limit:
        raise ValueError("Naver 수급 응답 크기가 허용 범위를 초과했습니다.")
    return payload


def _naver_trend_page(
    document: object,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)], None, False
    if not isinstance(document, dict):
        raise TypeError("Naver 수급 응답 형식이 객체 또는 목록이 아닙니다.")

    result = document.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)], None, False
    if isinstance(result, dict):
        rows = result.get("items")
        if isinstance(rows, list):
            cursor = str(result.get("cursor") or "").strip() or None
            return (
                [row for row in rows if isinstance(row, dict)],
                cursor,
                bool(result.get("hasNext")),
            )
    for key in ("list", "investorList", "investors", "trendList", "data"):
        rows = document.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)], None, False
    raise ValueError("Naver 수급 응답에 자료 목록이 없습니다.")


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _integer_value(value: object) -> int:
    if value is None:
        return 0
    text = str(value).strip().replace(",", "").replace("+", "")
    if not text or text in {"-", "--"}:
        return 0
    try:
        return int(round(float(text)))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Naver 수급 숫자 형식 오류: {value!r}") from error


def _trend_date(value: object) -> pd.Timestamp:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return pd.NaT
    return pd.to_datetime(digits[:8], format="%Y%m%d", errors="coerce")


def fetch_naver_investor_trend(
    ticker: object,
    *,
    count: int = NAVER_INVESTOR_TREND_COUNT,
    opener: Callable[..., object] | None = None,
) -> DataFrame:
    """Fetch aggregate net flows for one selected ticker, never market-wide.

    Naver exposes signed net-buy quantities for institutions, foreigners, and
    individuals. The chart's value series is an explicit estimate calculated
    as signed quantity multiplied by that day's close; nothing is persisted.
    """

    match = re.fullmatch(r"\d{1,6}", str(ticker).strip())
    if match is None:
        raise ValueError(f"종목코드 형식 오류: {ticker!r}")
    code = match.group(0).zfill(6)
    bounded_count = min(max(int(count), 1), NAVER_INVESTOR_TREND_COUNT)
    open_url = opener or urllib.request.urlopen
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    requested_urls: list[str] = []
    source_warning = ""
    while len(rows) < bounded_count:
        parameters = {
            "code": code,
            "exchangeType": "KRX",
            "size": min(NAVER_INVESTOR_PAGE_SIZE, bounded_count - len(rows)),
        }
        if cursor:
            parameters["cursor"] = cursor
        url = f"{NAVER_INVESTOR_TREND_URL}?{urllib.parse.urlencode(parameters)}"
        requested_urls.append(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": (
                    f"https://m.stock.naver.com/domestic/stock/{code}/tradingTrend"
                    "?stockEndTradingTrendExchange=KRX"
                ),
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/128 Safari/537.36"
                ),
                "x-for-krx-extension": "true",
            },
        )
        payload: bytes | None = None
        last_error: BaseException | None = None
        for _attempt in range(NAVER_INVESTOR_RETRIES):
            try:
                payload = _read_bounded_response(
                    open_url(request, timeout=NAVER_INVESTOR_TIMEOUT_SECONDS),
                    limit=NAVER_INVESTOR_MAX_RESPONSE_BYTES,
                )
                break
            except (TimeoutError, urllib.error.URLError) as error:
                last_error = error
        if payload is None:
            if not rows and last_error is not None:
                raise last_error
            source_warning = (
                "다음 수급 페이지 조회 실패로 확보된 구간까지만 표시합니다: "
                f"{type(last_error).__name__}"
            )
            break
        try:
            document = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Naver가 JSON이 아닌 수급 응답을 반환했습니다.") from error
        page_rows, next_cursor, has_next = _naver_trend_page(document)
        if not page_rows:
            break
        rows.extend(page_rows[: bounded_count - len(rows)])
        if not has_next or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    mappings = (
        (
            "INSTITUTION_TOTAL",
            (
                "organizationNetVolume",
                "organPureBuyQuant",
                "institutionPureBuyQuant",
            ),
        ),
        (
            "FOREIGN_TOTAL",
            ("foreignNetVolume", "foreignerPureBuyQuant", "foreignPureBuyQuant"),
        ),
        (
            "INDIVIDUAL",
            ("individualNetVolume", "individualPureBuyQuant", "personalPureBuyQuant"),
        ),
    )
    normalized: list[dict[str, object]] = []
    for row in rows:
        market_row = row.get("krx")
        values = {**row, **market_row} if isinstance(market_row, dict) else row
        trade_date = _trend_date(
            _first_value(
                values,
                "localTradedAt",
                "bizdate",
                "stcTrdDd",
                "bizday",
                "date",
            )
        )
        if pd.isna(trade_date):
            continue
        close_price = _integer_value(
            _first_value(
                values,
                "closingPrice",
                "closePrice",
                "close",
                "localTradedPrice",
            )
        )
        if close_price <= 0:
            continue
        for investor_type, keys in mappings:
            net_volume = _integer_value(_first_value(values, *keys))
            net_value = net_volume * close_price
            normalized.append(
                {
                    "stock_code": code,
                    "trade_date": trade_date,
                    "investor_type": investor_type,
                    "buy_volume": max(net_volume, 0),
                    "sell_volume": max(-net_volume, 0),
                    "buy_value": max(net_value, 0),
                    "sell_value": max(-net_value, 0),
                    "source": "NAVER:FRONT_TREND_PUBLIC",
                    "source_url": NAVER_INVESTOR_TREND_URL,
                    "source_date": trade_date,
                }
            )
    if not normalized:
        raise ValueError(f"Naver 공개 수급 응답에 {code}의 유효한 행이 없습니다.")
    frame = DataFrame(normalized).drop_duplicates(
        ["stock_code", "trade_date", "investor_type"], keep="last"
    )
    frame = frame.sort_values(["trade_date", "investor_type"], ignore_index=True)
    frame.attrs = {
        "source": "NAVER:FRONT_TREND_PUBLIC",
        "source_url": NAVER_INVESTOR_TREND_URL,
        "source_label": "Naver 공개 수급 · 순매수수량×종가 추정",
        "estimated_value": True,
        "source_rows": int(frame["trade_date"].nunique()),
        "source_requests": len(requested_urls),
        "source_warning": source_warning,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return frame


def _investor_frames(raw: DataFrame) -> dict[str, DataFrame]:
    metadata = dict(getattr(raw, "attrs", {})) if raw is not None else {}

    def empty() -> DataFrame:
        frame = DataFrame(
            columns=["institution", "foreign", "individual"],
            index=pd.DatetimeIndex([], name="trade_date"),
        )
        frame.attrs.update(metadata)
        return frame
    if raw is None or raw.empty or not {"trade_date", "investor_type"}.issubset(raw.columns):
        return {timeframe: empty() for timeframe in TIMEFRAME_LABELS}

    clean = raw.copy()
    clean["trade_date"] = pd.to_datetime(clean["trade_date"], errors="coerce")

    def safe_code(value: object) -> str | None:
        try:
            return normalize_investor_code(str(value))
        except (TypeError, ValueError):
            return None

    clean["investor_type"] = clean["investor_type"].map(safe_code)
    clean = clean.loc[
        clean["trade_date"].notna() & clean["investor_type"].notna()
    ].copy()
    if clean.empty:
        return {timeframe: empty() for timeframe in TIMEFRAME_LABELS}

    output: dict[str, DataFrame] = {}
    for timeframe in TIMEFRAME_LABELS:
        aggregated = aggregate_investor_flow(clean, timeframe, include_totals=True)
        if aggregated.empty:
            output[timeframe] = empty()
            continue
        selected = aggregated.loc[
            aggregated["investor_type"].isin(
                ["INSTITUTION_TOTAL", "FOREIGN_TOTAL", "INDIVIDUAL"]
            )
        ]
        pivot = selected.pivot_table(
            index="trade_date",
            columns="investor_type",
            values="net_value",
            aggfunc="sum",
            fill_value=0,
        ).rename(
            columns={
                "INSTITUTION_TOTAL": "institution",
                "FOREIGN_TOTAL": "foreign",
                "INDIVIDUAL": "individual",
            }
        )
        for column in ("institution", "foreign", "individual"):
            if column not in pivot:
                # Keep an entirely unavailable category distinct from a true
                # zero net flow on a date for which that category was supplied.
                pivot[column] = np.nan
        pivot.index = pd.DatetimeIndex(pd.to_datetime(pivot.index), name="trade_date")
        result = pivot[
            ["institution", "foreign", "individual"]
        ].sort_index()
        result.attrs.update(metadata)
        output[timeframe] = result
    return output


class PostgreSQLOnDemandData:
    """Thread-safe GUI facade over the PostgreSQL fact tables."""

    def __init__(
        self,
        target: PostgreSQLSettings,
        *,
        cache_seconds: int = SCREEN_CACHE_SECONDS,
    ) -> None:
        self.target = target
        self.settings = settings_from_database_target(target)
        self.cache_seconds = max(0, int(cache_seconds))
        self._screen_cache: dict[tuple[object, ...], tuple[float, OnDemandScreenResult]] = {}
        self._master_cache: tuple[float, DataFrame] | None = None
        self._investor_cache: dict[str, tuple[float, DataFrame]] = {}
        self._chart_raw_cache: dict[str, tuple[float, DataFrame]] = {}
        self._chart_frame_cache: dict[
            tuple[str, str], tuple[float, DataFrame]
        ] = {}
        self._security_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    def _master(self, repository: BaseDataRepository) -> DataFrame:
        now = self._now()
        with self._lock:
            cached = self._master_cache
            if cached is not None and now - cached[0] <= self.cache_seconds:
                return cached[1].copy(deep=True)
        frame = repository.get_security_master_frame()
        with self._lock:
            self._master_cache = (now, frame.copy(deep=True))
        return frame

    def _screen_cache_get(
        self,
        key: tuple[object, ...],
        now: float,
    ) -> OnDemandScreenResult | None:
        with self._lock:
            cached = self._screen_cache.get(key)
            if cached is None or now - cached[0] > self.cache_seconds:
                return None
            return cached[1]

    def _screen_cache_set(
        self,
        key: tuple[object, ...],
        now: float,
        value: OnDemandScreenResult,
    ) -> None:
        with self._lock:
            self._screen_cache[key] = (now, value)

    def _trim_chart_cache_locked(self) -> None:
        """Keep chart reuse useful without retaining every visited stock."""

        while len(self._chart_raw_cache) > CHART_CACHE_MAX_TICKERS:
            oldest_code = next(iter(self._chart_raw_cache))
            self._chart_raw_cache.pop(oldest_code, None)
            self._security_cache.pop(oldest_code, None)
            self._investor_cache.pop(oldest_code, None)
            for cache_key in tuple(self._chart_frame_cache):
                if cache_key[0] == oldest_code:
                    self._chart_frame_cache.pop(cache_key, None)

    def resolve_ticker(self, ticker_or_name: object) -> str:
        query = str(ticker_or_name).strip()
        if not query:
            raise ValueError("종목명 또는 6자리 종목코드를 입력하세요.")
        if query.isdigit():
            return query.zfill(6)
        with BaseDataRepository(self.settings) as repository:
            master = self._master(repository)
        matches = master.loc[
            master["stock_name"].fillna("").astype(str).str.casefold().eq(query.casefold())
        ]
        if matches.empty:
            raise ValueError(f"종목명 '{query}'을 종목 마스터에서 찾을 수 없습니다.")
        if len(matches) > 1:
            codes = ", ".join(matches["stock_code"].astype(str).tolist())
            raise ValueError(f"종목명 '{query}'이 여러 종목과 일치합니다: {codes}")
        return str(matches.iloc[0]["stock_code"]).zfill(6)

    def load_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None = None,
        comparison_ticker: str = "222800",
        venue: str = "KRX",
        cancel_event: threading.Event | None = None,
    ) -> OnDemandScreenResult:
        requested = None if as_of_date is None else pd.Timestamp(as_of_date).date()
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        _raise_if_cancelled(cancel_event)
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date() if venue == "KRX" else repository.latest_venue_ohlcv_date(venue)
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            end_date = min(latest, requested) if requested is not None else latest
            cache_key = (venue, screen_type, end_date)
            now = self._now()
            value = self._screen_cache_get(cache_key, now)
            if value is not None:
                return OnDemandScreenResult(
                    rows=value.rows.copy(deep=True),
                    as_of_date=value.as_of_date,
                    universe_count=value.universe_count,
                )
            lookback = SCREEN_LOOKBACK_DAYS[screen_type]
            start_date = end_date - dt.timedelta(days=lookback)
            raw = repository.get_market_ohlcv(start_date, end_date) if venue == "KRX" else repository.get_venue_ohlcv(venue, start_date, end_date)
            _raise_if_cancelled(cancel_event)
            history, actual_date = _prepare_history(raw, self._master(repository))
            if requested is not None and actual_date != requested:
                raise ValueError(
                    f"선택한 {requested.isoformat()} 자료가 완전하지 않습니다. "
                    f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                )
            rows = calculate_screen(
                history,
                screen_type,
                comparison_ticker=comparison_ticker,
            )
            _raise_if_cancelled(cancel_event)
            universe_count = int(history.loc[
                history["trade_date"].dt.date.eq(actual_date), "ticker"
            ].nunique())
            value = OnDemandScreenResult(rows, actual_date, universe_count)
            self._screen_cache_set(cache_key, now, value)
            return OnDemandScreenResult(
                rows=rows.copy(deep=True),
                as_of_date=actual_date,
                universe_count=universe_count,
            )

    def load_screen_period(
        self,
        screen_type: str,
        as_of_dates: list[dt.date] | tuple[dt.date, ...],
        *,
        comparison_ticker: str = "222800",
        venue: str = "KRX",
        cancel_event: threading.Event | None = None,
    ) -> list[OnDemandScreenResult]:
        """Calculate several dated screens from one PostgreSQL bulk read.

        Each snapshot is still calculated from its own bounded lookback so a
        later corporate action cannot leak into an earlier result.  The costly
        all-market SQL query and security-master query are shared by the whole
        request.
        """

        _raise_if_cancelled(cancel_event)
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        requested_dates = sorted(
            {pd.Timestamp(value).date() for value in as_of_dates}
        )
        if not requested_dates:
            return []
        if screen_type not in SCREEN_LOOKBACK_DAYS:
            raise ValueError(f"지원하지 않는 스크리닝: {screen_type}")

        lookback = SCREEN_LOOKBACK_DAYS[screen_type]
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date() if venue == "KRX" else repository.latest_venue_ohlcv_date(venue)
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            if requested_dates[-1] > latest:
                raise ValueError(
                    f"선택한 {requested_dates[-1].isoformat()} 자료가 없습니다. "
                    f"PostgreSQL 최신 기준일은 {latest.isoformat()}입니다."
                )

            now = self._now()
            cached_results: dict[dt.date, OnDemandScreenResult] = {}
            missing_dates: list[dt.date] = []
            for screen_date in requested_dates:
                cached = self._screen_cache_get((venue, screen_type, screen_date), now)
                if cached is not None:
                    cached_results[screen_date] = cached
                else:
                    missing_dates.append(screen_date)

            if missing_dates:
                raw_start = missing_dates[0] - dt.timedelta(days=lookback)
                raw_end = missing_dates[-1]
                raw = repository.get_market_ohlcv(raw_start, raw_end) if venue == "KRX" else repository.get_venue_ohlcv(venue, raw_start, raw_end)
                _raise_if_cancelled(cancel_event)
                if raw.empty:
                    raise ValueError("선택 기간의 PostgreSQL 일봉 원천자료가 없습니다.")
                raw_dates = pd.to_datetime(raw["trade_date"], errors="coerce").dt.date
                master = self._master(repository)

                for screen_date in missing_dates:
                    _raise_if_cancelled(cancel_event)
                    window_start = screen_date - dt.timedelta(days=lookback)
                    window_mask = raw_dates.between(window_start, screen_date)
                    history, actual_date = _prepare_history(
                        raw.loc[window_mask].copy(),
                        master,
                    )
                    if actual_date != screen_date:
                        raise ValueError(
                            f"선택한 {screen_date.isoformat()} 자료가 완전하지 않습니다. "
                            f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                        )
                    rows = calculate_screen(
                        history,
                        screen_type,
                        comparison_ticker=comparison_ticker,
                    )
                    _raise_if_cancelled(cancel_event)
                    universe_count = int(
                        history.loc[
                            history["trade_date"].dt.date.eq(actual_date),
                            "ticker",
                        ].nunique()
                    )
                    value = OnDemandScreenResult(rows, actual_date, universe_count)
                    self._screen_cache_set(
                        (venue, screen_type, screen_date), now, value
                    )
                    cached_results[screen_date] = value

        return [
            OnDemandScreenResult(
                rows=cached_results[screen_date].rows.copy(deep=True),
                as_of_date=cached_results[screen_date].as_of_date,
                universe_count=cached_results[screen_date].universe_count,
            )
            for screen_date in requested_dates
        ]

    def load_overlay_snapshot(
        self,
        *,
        as_of_date: object | None = None,
        venue: str = "KRX",
    ) -> OnDemandScreenResult:
        """Return all calculated fields required by the real-time radio mode."""

        requested = None if as_of_date is None else pd.Timestamp(as_of_date).date()
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date() if venue == "KRX" else repository.latest_venue_ohlcv_date(venue)
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            end_date = min(latest, requested) if requested is not None else latest
            cache_key = (venue, "__overlay__", end_date)
            now = self._now()
            value = self._screen_cache_get(cache_key, now)
            if value is not None:
                return OnDemandScreenResult(
                    value.rows.copy(deep=True),
                    value.as_of_date,
                    value.universe_count,
                )
            start = end_date - dt.timedelta(days=SCREEN_LOOKBACK_DAYS["ema_similarity"])
            raw = repository.get_market_ohlcv(start, end_date) if venue == "KRX" else repository.get_venue_ohlcv(venue, start, end_date)
            history, actual_date = _prepare_history(raw, self._master(repository))
            if requested is not None and actual_date != requested:
                raise ValueError(
                    f"선택한 {requested.isoformat()} 자료가 완전하지 않습니다. "
                    f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                )
            rows = build_overlay_snapshot(history)
            universe_count = len(rows)
            value = OnDemandScreenResult(rows, actual_date, universe_count)
            self._screen_cache_set(cache_key, now, value)
            return OnDemandScreenResult(
                rows.copy(deep=True),
                actual_date,
                universe_count,
            )

    def load_overlay_period(
        self,
        as_of_dates: list[dt.date] | tuple[dt.date, ...],
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[OnDemandScreenResult]:
        """Build full dated cross-sections from one shared PostgreSQL read."""

        _raise_if_cancelled(cancel_event)
        requested_dates = sorted(
            {pd.Timestamp(value).date() for value in as_of_dates}
        )
        if not requested_dates:
            return []
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date()
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            if requested_dates[-1] > latest:
                raise ValueError(
                    f"선택한 {requested_dates[-1].isoformat()} 자료가 없습니다. "
                    f"PostgreSQL 최신 기준일은 {latest.isoformat()}입니다."
                )

            now = self._now()
            cached_results: dict[dt.date, OnDemandScreenResult] = {}
            missing_dates: list[dt.date] = []
            for screen_date in requested_dates:
                cached = self._screen_cache_get(("__overlay__", screen_date), now)
                if cached is None:
                    missing_dates.append(screen_date)
                else:
                    cached_results[screen_date] = cached

            if missing_dates:
                lookback = SCREEN_LOOKBACK_DAYS["ema_similarity"]
                raw_start = missing_dates[0] - dt.timedelta(days=lookback)
                raw = repository.get_market_ohlcv(raw_start, missing_dates[-1])
                _raise_if_cancelled(cancel_event)
                if raw.empty:
                    raise ValueError("선택 기간의 PostgreSQL 일봉 원천자료가 없습니다.")
                raw_dates = pd.to_datetime(raw["trade_date"], errors="coerce").dt.date
                master = self._master(repository)
                for screen_date in missing_dates:
                    _raise_if_cancelled(cancel_event)
                    window_start = screen_date - dt.timedelta(days=lookback)
                    window_mask = raw_dates.between(window_start, screen_date)
                    history, actual_date = _prepare_history(
                        raw.loc[window_mask].copy(),
                        master,
                    )
                    if actual_date != screen_date:
                        raise ValueError(
                            f"선택한 {screen_date.isoformat()} 자료가 완전하지 않습니다. "
                            f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                        )
                    rows = build_overlay_snapshot(history)
                    _raise_if_cancelled(cancel_event)
                    value = OnDemandScreenResult(rows, actual_date, len(rows))
                    self._screen_cache_set(("__overlay__", screen_date), now, value)
                    cached_results[screen_date] = value

        return [
            OnDemandScreenResult(
                rows=cached_results[screen_date].rows.copy(deep=True),
                as_of_date=cached_results[screen_date].as_of_date,
                universe_count=cached_results[screen_date].universe_count,
            )
            for screen_date in requested_dates
        ]

    def load_chart(
        self,
        ticker_or_name: object,
        *,
        timeframes: tuple[str, ...] = ("D", "W"),
        include_investor: bool = False,
        live_bar: dict[str, object] | None = None,
        venue: str = "KRX",
        cancel_event: threading.Event | None = None,
    ) -> OnDemandChartResult:
        """Load only requested chart components with short-lived reusable caches."""

        _raise_if_cancelled(cancel_event)
        code = self.resolve_ticker(ticker_or_name)
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        cache_code = f"{venue}:{code}"
        selected_timeframes = tuple(
            dict.fromkeys(str(value).strip().upper() for value in timeframes)
        )
        invalid = [value for value in selected_timeframes if value not in TIMEFRAME_LABELS]
        if invalid:
            raise ValueError(f"지원하지 않는 봉 주기: {invalid[0]!r}")
        now = self._now()
        with self._lock:
            cached_raw = self._chart_raw_cache.get(cache_code)
            raw = (
                cached_raw[1].copy(deep=True)
                if cached_raw is not None
                and now - cached_raw[0] <= CHART_CACHE_SECONDS
                else None
            )
            cached_security = self._security_cache.get(cache_code)
            security_row = (
                dict(cached_security[1])
                if cached_security is not None
                and now - cached_security[0] <= CHART_CACHE_SECONDS
                else None
            )
            cached_investor = self._investor_cache.get(cache_code)
            investor_raw = (
                cached_investor[1].copy(deep=True)
                if include_investor
                and cached_investor is not None
                and now - cached_investor[0] <= NAVER_INVESTOR_CACHE_SECONDS
                else None
            )

        needs_database = (
            raw is None
            or security_row is None
            or (include_investor and investor_raw is None)
        )
        if needs_database:
            with BaseDataRepository(self.settings) as repository:
                if raw is None:
                    if venue == "KRX":
                        raw = repository.get_ohlcv(code)
                    else:
                        raw = repository.get_venue_ohlcv(venue, ticker=code)
                    if raw.empty:
                        raise ValueError(f"{code}의 {venue} 일봉 원천자료가 없습니다.")
                if security_row is None:
                    master = self._master(repository)
                    security = master.loc[
                        master["stock_code"].astype(str).eq(code)
                    ]
                    security_row = (
                        security.iloc[0].to_dict() if not security.empty else {}
                    )
                if include_investor and investor_raw is None:
                    investor_raw = repository.get_investor_flow(code)
            _raise_if_cancelled(cancel_event)
            with self._lock:
                self._chart_raw_cache.pop(cache_code, None)
                self._chart_raw_cache[cache_code] = (now, raw.copy(deep=True))
                self._security_cache[cache_code] = (now, dict(security_row or {}))
                self._trim_chart_cache_locked()

        if raw is None:
            raise ValueError(f"{code}의 PostgreSQL 일봉 원천자료가 없습니다.")
        if include_investor and investor_raw is not None and investor_raw.empty:
            investor_raw.attrs = {
                "source": "LS:SOURCE_PENDING_NORMALIZATION",
                "source_label": "LS 화면용 수급 미적재",
                "source_error": "LS 원본은 별도 저장됩니다. 금액 단위·투자자 코드 검증 전에는 화면용 수급으로 사용하지 않습니다.",
            }
        elif include_investor and investor_raw is not None:
            sources = []
            if "source" in investor_raw:
                sources = sorted(
                    investor_raw["source"].dropna().astype(str).unique().tolist()
                )
            investor_raw.attrs.update(
                {
                    "source": ", ".join(sources) or "PostgreSQL",
                    "source_label": investor_raw.attrs.get("source_label", "PostgreSQL 저장 수급 원천"),
                    "estimated_value": investor_raw.attrs.get("estimated_value", False),
                }
            )
        if include_investor and investor_raw is not None:
            with self._lock:
                self._investor_cache[cache_code] = (
                    now,
                    investor_raw.copy(deep=True),
                )

        chart_raw, has_live_bar = _append_live_chart_bar(raw, code, live_bar)
        bars: dict[str, DataFrame] = {}
        for timeframe in selected_timeframes:
            _raise_if_cancelled(cancel_event)
            cache_key = (cache_code, timeframe)
            with self._lock:
                cached_frame = None if has_live_bar else self._chart_frame_cache.get(cache_key)
                frame = (
                    cached_frame[1].copy(deep=True)
                    if cached_frame is not None
                    and now - cached_frame[0] <= CHART_CACHE_SECONDS
                    else None
                )
            if frame is None:
                frame = _chart_frame(chart_raw, timeframe)
                if not has_live_bar:
                    with self._lock:
                        self._chart_frame_cache[cache_key] = (
                            now,
                            frame.copy(deep=True),
                        )
            bars[timeframe] = frame
        _raise_if_cancelled(cancel_event)
        row = security_row or {}

        def text_value(key: str, fallback: str = "") -> str:
            value = row.get(key) if hasattr(row, "get") else None
            return fallback if value is None or pd.isna(value) else str(value)

        return OnDemandChartResult(
            ticker=code,
            name=text_value("stock_name", code),
            market=text_value("market"),
            industry=text_value("industry"),
            bars=bars,
            investor=(
                _investor_frames(investor_raw)
                if include_investor and investor_raw is not None
                else {}
            ),
        )


__all__ = [
    "OnDemandChartResult",
    "OnDemandScreenResult",
    "PostgreSQLOnDemandData",
    "CHART_CACHE_MAX_TICKERS",
    "CHART_CACHE_SECONDS",
    "SCREEN_CACHE_SECONDS",
    "TIMEFRAME_LABELS",
    "build_overlay_snapshot",
    "calculate_screen",
    "fetch_naver_investor_trend",
]
