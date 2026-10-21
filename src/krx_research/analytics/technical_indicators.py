"""Pure technical-indicator calculations for adjusted KRX OHLCV history."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

import pandas as pd
from pandas import DataFrame, Series

from krx_research.collectors import normalize_ticker
from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY

EMA_WINDOWS = DEFAULT_CHART_ANALYSIS_POLICY.moving_average_periods
TRADING_DAYS_52W = 252
BOLLINGER_WEEKS = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
BOLLINGER_STDDEV = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.deviations
FORMULA_VERSION = 3


@dataclass(frozen=True)
class TechnicalIndicatorResult:
    """Daily and weekly deterministic indicator frames for one ticker."""

    ticker: str
    daily: DataFrame
    weekly: DataFrame
    observations: int
    history_ready_448: bool


def _nullable_flag(condition: Series, available: Series) -> Series:
    result = Series(pd.NA, index=condition.index, dtype="Int64")
    result.loc[available] = condition.loc[available].astype("int64")
    return result


def exponential_moving_average(close: Series, period: int) -> Series:
    """Return the repository-standard EMA without database side effects."""
    if period < 1:
        raise ValueError("EMA period must be at least 1")
    return pd.to_numeric(close, errors="coerce").astype("float64").ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).mean()


def _normalized_ohlcv(frame: DataFrame, ticker: object | None) -> tuple[str, DataFrame]:
    if frame.empty:
        raise ValueError("OHLCV history is empty")

    required = {"open", "high", "low", "close", "volume"}
    if missing := required.difference(frame.columns):
        raise ValueError(f"OHLCV history missing columns: {sorted(missing)}")

    work = frame.copy()
    if "trade_date" in work:
        index = pd.DatetimeIndex(pd.to_datetime(work.pop("trade_date"), errors="raise"))
    elif "date" in work:
        index = pd.DatetimeIndex(pd.to_datetime(work.pop("date"), errors="raise"))
    else:
        index = pd.DatetimeIndex(pd.to_datetime(work.index, errors="raise"))
    work.index = index.tz_localize(None).normalize()
    work.index.name = "trade_date"
    work = work.sort_index()
    if work.index.duplicated().any():
        raise ValueError("OHLCV history contains duplicate trade dates")

    if ticker is None:
        if "ticker" not in work:
            raise ValueError("ticker is required when OHLCV history has no ticker column")
        codes = {normalize_ticker(value) for value in work["ticker"]}
        if len(codes) != 1:
            raise ValueError(f"Expected one ticker in OHLCV history, received {sorted(codes)}")
        code = codes.pop()
    else:
        code = normalize_ticker(ticker)
        if "ticker" in work:
            codes = {normalize_ticker(value) for value in work["ticker"]}
            if codes != {code}:
                raise ValueError(f"OHLCV ticker mismatch: expected {code}, received {sorted(codes)}")

    for column in required:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if work[list(required)].isna().any().any():
        raise ValueError("OHLCV history contains missing or non-numeric values")
    invalid = (
        (work["volume"] < 0)
        | (work["high"] < work[["open", "low", "close"]].max(axis=1))
        | (work["low"] > work[["open", "high", "close"]].min(axis=1))
    )
    if invalid.any():
        dates = work.index[invalid].strftime("%Y-%m-%d").tolist()
        raise ValueError(f"OHLCV history contains invalid rows: {dates[:10]}")
    return code, work


def _daily_indicators(code: str, work: DataFrame, calculated_at: str) -> DataFrame:
    daily = DataFrame(index=work.index)
    daily["ticker"] = code
    daily["close"] = work["close"].astype("float64")
    daily["observations"] = range(1, len(work) + 1)

    ema_columns: list[str] = []
    for window in EMA_WINDOWS:
        column = f"ema_{window}"
        ema_columns.append(column)
        daily[column] = exponential_moving_average(work["close"], window)

    prior_high = work["high"].shift(1).rolling(
        TRADING_DAYS_52W,
        min_periods=1,
    ).max()
    high_52w = work["high"].rolling(
        TRADING_DAYS_52W,
        min_periods=1,
    ).max()
    daily["prior_high_52w"] = prior_high
    daily["high_52w"] = high_52w
    daily["distance_from_52w_high_pct"] = (daily["close"] / high_52w - 1.0) * 100.0
    daily["is_52w_high"] = _nullable_flag(
        work["high"] >= high_52w,
        high_52w.notna(),
    )
    daily["is_52w_breakout"] = _nullable_flag(
        work["high"] > prior_high,
        prior_high.notna(),
    )

    ready = daily[ema_columns].notna().all(axis=1)
    bullish = ready.copy()
    bearish = ready.copy()
    for shorter, longer in pairwise(ema_columns):
        bullish &= daily[shorter] > daily[longer]
        bearish &= daily[shorter] < daily[longer]
    daily["ema_alignment"] = "insufficient"
    daily.loc[ready, "ema_alignment"] = "mixed"
    daily.loc[bullish, "ema_alignment"] = "bullish"
    daily.loc[bearish, "ema_alignment"] = "bearish"
    daily["close_above_ema5"] = _nullable_flag(
        daily["close"] > daily["ema_5"],
        daily["ema_5"].notna(),
    )
    daily["formula_version"] = FORMULA_VERSION
    daily["calculated_at"] = calculated_at
    return daily


def _weekly_indicators(code: str, work: DataFrame, calculated_at: str) -> DataFrame:
    grouped = work.assign(
        trade_date=work.index,
        week_end=work.index.to_period("W-FRI").end_time.normalize(),
    ).groupby("week_end", sort=True)
    weekly = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        trading_days=("close", "size"),
        last_trade_date=("trade_date", "max"),
    )
    weekly.index = pd.DatetimeIndex(weekly.index, name="week_end")
    weekly.insert(0, "ticker", code)
    weekly["previous_close"] = weekly["close"].shift(1)
    weekly["weekly_return_pct"] = weekly["close"].pct_change(fill_method=None) * 100.0

    rolling = weekly["close"].rolling(BOLLINGER_WEEKS, min_periods=BOLLINGER_WEEKS)
    weekly["bb_mid_20"] = weekly["close"].ewm(
        span=BOLLINGER_WEEKS, adjust=False, min_periods=BOLLINGER_WEEKS
    ).mean()
    deviation = rolling.std(ddof=0)
    weekly["bb_upper_20_2"] = weekly["bb_mid_20"] + BOLLINGER_STDDEV * deviation
    weekly["bb_lower_20_2"] = weekly["bb_mid_20"] - BOLLINGER_STDDEV * deviation
    available_band = weekly["bb_upper_20_2"].notna()
    weekly["is_bb_upper_breakout"] = _nullable_flag(
        weekly["close"] > weekly["bb_upper_20_2"],
        available_band,
    )
    weekly["formula_version"] = FORMULA_VERSION
    weekly["calculated_at"] = calculated_at
    return weekly


def calculate_technical_indicators(
    frame: DataFrame,
    *,
    ticker: object | None = None,
) -> TechnicalIndicatorResult:
    """Calculate look-ahead-safe indicators from one adjusted OHLCV history."""

    code, work = _normalized_ohlcv(frame, ticker)
    calculated_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    daily = _daily_indicators(code, work, calculated_at)
    weekly = _weekly_indicators(code, work, calculated_at)
    return TechnicalIndicatorResult(
        ticker=code,
        daily=daily,
        weekly=weekly,
        observations=len(work),
        history_ready_448=len(work) >= max(EMA_WINDOWS),
    )


def calculate_incremental_technical_indicators(
    frame: DataFrame,
    *,
    ticker: object,
    append_after: object,
    previous_daily: Mapping[str, object],
    total_observations: int,
) -> TechnicalIndicatorResult:
    """Calculate an exact pure-tail update without replaying the full history.

    ``frame`` must contain the last 252 stored sessions through the new tail.
    The prior persisted EMA values provide the recursive state required by
    ``ewm(adjust=False)``.  Weekly indicators only need 20 weeks, so the same
    252-session window is more than sufficient for an exact appended result.
    """

    code, work = _normalized_ohlcv(frame, ticker)
    cutoff = pd.Timestamp(append_after)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    cutoff = cutoff.normalize()
    if cutoff not in work.index:
        raise ValueError("Incremental OHLCV window does not contain append_after")

    tail = work.loc[work.index > cutoff]
    prior_window = work.loc[work.index <= cutoff]
    if tail.empty:
        raise ValueError("Incremental OHLCV window has no appended rows")
    if len(prior_window) < TRADING_DAYS_52W:
        raise ValueError("Incremental OHLCV window needs 252 prior sessions")

    try:
        previous_observations = int(previous_daily["observations"])
        previous_close = float(previous_daily["close"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Previous daily indicator state is incomplete") from error
    if previous_observations < max(EMA_WINDOWS):
        raise ValueError("Incremental EMA state is not fully warmed up")
    if previous_observations + len(tail) != total_observations:
        raise ValueError("Incremental observation count does not match the input signature")
    if not math.isclose(
        previous_close,
        float(work.loc[cutoff, "close"]),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError("Previous indicator close does not match OHLCV")

    previous_emas: dict[int, float] = {}
    for window in EMA_WINDOWS:
        value = previous_daily.get(f"ema_{window}")
        if value is None or pd.isna(value):
            raise ValueError(f"Previous ema_{window} state is unavailable")
        previous_emas[window] = float(value)

    calculated_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    daily = DataFrame(index=tail.index)
    daily["ticker"] = code
    daily["close"] = tail["close"].astype("float64")
    daily["observations"] = range(previous_observations + 1, total_observations + 1)

    ema_columns: list[str] = []
    for window in EMA_WINDOWS:
        column = f"ema_{window}"
        ema_columns.append(column)
        alpha = 2.0 / (window + 1.0)
        current = previous_emas[window]
        values: list[float] = []
        for close in daily["close"]:
            current = (1.0 - alpha) * current + alpha * float(close)
            values.append(current)
        daily[column] = values

    prior_high = work["high"].shift(1).rolling(
        TRADING_DAYS_52W,
        min_periods=1,
    ).max()
    high_52w = work["high"].rolling(
        TRADING_DAYS_52W,
        min_periods=1,
    ).max()
    daily["prior_high_52w"] = prior_high.reindex(tail.index)
    daily["high_52w"] = high_52w.reindex(tail.index)
    daily["distance_from_52w_high_pct"] = (
        daily["close"] / daily["high_52w"] - 1.0
    ) * 100.0
    daily["is_52w_high"] = _nullable_flag(
        tail["high"] >= daily["high_52w"],
        daily["high_52w"].notna(),
    )
    daily["is_52w_breakout"] = _nullable_flag(
        tail["high"] > daily["prior_high_52w"],
        daily["prior_high_52w"].notna(),
    )

    ready = daily[ema_columns].notna().all(axis=1)
    bullish = ready.copy()
    bearish = ready.copy()
    for shorter, longer in pairwise(ema_columns):
        bullish &= daily[shorter] > daily[longer]
        bearish &= daily[shorter] < daily[longer]
    daily["ema_alignment"] = "insufficient"
    daily.loc[ready, "ema_alignment"] = "mixed"
    daily.loc[bullish, "ema_alignment"] = "bullish"
    daily.loc[bearish, "ema_alignment"] = "bearish"
    daily["close_above_ema5"] = _nullable_flag(
        daily["close"] > daily["ema_5"],
        daily["ema_5"].notna(),
    )
    daily["formula_version"] = FORMULA_VERSION
    daily["calculated_at"] = calculated_at

    weekly = _weekly_indicators(code, work, calculated_at)
    return TechnicalIndicatorResult(
        ticker=code,
        daily=daily,
        weekly=weekly,
        observations=total_observations,
        history_ready_448=total_observations >= max(EMA_WINDOWS),
    )
