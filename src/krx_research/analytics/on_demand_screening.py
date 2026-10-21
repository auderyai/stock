"""Pure in-memory calculations for on-demand stock screening."""

from __future__ import annotations

import datetime as dt
import re

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics.ema_similarity import (
    EMA_DEFAULT_GAP_TOLERANCE,
    EMA_DEFAULT_MIN_SIMILARITY,
    calculate_ema_similarity_metrics,
)
from krx_research.analytics.technical_indicators import FORMULA_VERSION
from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY

EMA_WINDOWS = DEFAULT_CHART_ANALYSIS_POLICY.moving_average_periods
BOLLINGER_PERIOD = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
BOLLINGER_DEVIATIONS = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.deviations
PRICE_ADJUSTMENT_RATIO_TOLERANCE = 0.02
SPAC_PATTERN = re.compile(
    r"(?:스\\s*팩|기업인수목적|(?<![A-Za-z])SPAC(?![A-Za-z]))",
    flags=re.IGNORECASE,
)


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
        lambda values: values.ewm(
            span=BOLLINGER_PERIOD, adjust=False, min_periods=BOLLINGER_PERIOD
        ).mean()
    )
    deviation = grouped["close"].transform(
        lambda values: values.rolling(
            BOLLINGER_PERIOD, min_periods=BOLLINGER_PERIOD
        ).std(ddof=0)
    )
    weekly["bb_upper_20_2"] = (
        weekly["bb_mid_20"] + BOLLINGER_DEVIATIONS * deviation
    )
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
