"""Pure screening calculations shared by workstation services and repositories."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics import exclude_spac_securities
from krx_research.collectors.index_membership import IndexMembership
from krx_research.collectors.market_data import normalize_ticker
from krx_research.collectors.realtime_quotes import RealtimeQuoteSnapshot
from krx_research.analytics.investor import FOREIGN_MEMBERS, INSTITUTION_MEMBERS
from krx_research.policies.screen_catalog import (
    INVESTOR_FLOW_SCREEN_DEFINITIONS,
    MARKET_GAINER_DEFINITIONS,
    MARKET_GAINER_SCREEN_TYPES,
    MARKET_RESULT_DEFINITIONS,
    MARKET_TRADING_VALUE_DEFINITIONS,
    MARKET_TRADING_VALUE_SCREEN_TYPES,
    MARKET_WEEKLY_GAINER_DEFINITIONS,
    MARKET_WEEKLY_GAINER_SCREEN_TYPES,
    WEEKLY_SCREEN_TYPES,
    WEEKLY_TRADING_VALUE_DEFINITIONS,
    WEEKLY_TRADING_VALUE_SCREEN_TYPES,
)

REALTIME_ADJUSTMENT_RATIO_TOLERANCE = 0.02


def build_repeated_screen_rows(
    rows: pd.DataFrame,
    *,
    minimum_count: int = 2,
) -> pd.DataFrame:
    """Return period results whose ticker appears at least ``minimum_count`` times."""

    if rows is None or rows.empty or "ticker" not in rows.columns:
        return pd.DataFrame()
    if minimum_count < 1:
        raise ValueError("minimum_count는 1 이상이어야 합니다.")
    frame = rows.copy()
    counts = frame.groupby("ticker", dropna=False).size().rename("appearance_count")
    repeated = frame.merge(counts, left_on="ticker", right_index=True)
    repeated = repeated.loc[repeated["appearance_count"] >= minimum_count].copy()
    sort_columns = [
        column
        for column in ("appearance_count", "ticker", "screen_date")
        if column in repeated.columns
    ]
    if sort_columns:
        repeated = repeated.sort_values(
            sort_columns,
            ascending=[False] + [True] * (len(sort_columns) - 1),
        )
    return repeated.reset_index(drop=True)


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
