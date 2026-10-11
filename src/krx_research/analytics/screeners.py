"""Cross-sectional KRX screens over persisted technical-indicator snapshots."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import pandas as pd
from pandas import DataFrame

from krx_research.collectors import normalize_ticker

from .ema_similarity import (
    EMA_DEFAULT_GAP_TOLERANCE,
    EMA_DEFAULT_MIN_SIMILARITY,
    calculate_ema_similarity_metrics,
    validate_ema_similarity_options,
)
from .technical_indicators import EMA_WINDOWS, FORMULA_VERSION

SCREEN_TYPES = (
    "ema_similarity",
    "high_52w",
    "bollinger_breakout",
    "weekly_return",
)
SCREEN_FORMULA_VERSION = 4
SPAC_NAME_PATTERN = re.compile(
    r"(?:스\s*팩|기업인수목적|(?<![A-Za-z])SPAC(?![A-Za-z]))",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ScreeningResult:
    """Ranked screen frames produced from one same-date market snapshot."""

    as_of_date: dt.date
    comparison_ticker: str | None
    universe_count: int
    ema_similarity: DataFrame
    high_52w: DataFrame
    bollinger_breakout: DataFrame
    weekly_return: DataFrame

    def frames(self) -> dict[str, DataFrame]:
        return {
            "ema_similarity": self.ema_similarity,
            "high_52w": self.high_52w,
            "bollinger_breakout": self.bollinger_breakout,
            "weekly_return": self.weekly_return,
        }


def exclude_spac_securities(frame: DataFrame) -> DataFrame:
    """Remove SPAC securities by their KRX master name and close rank gaps."""

    if "name" not in frame.columns or frame.empty:
        return frame.copy()
    names = frame["name"].astype("string").fillna("")
    result = frame.loc[~names.str.contains(SPAC_NAME_PATTERN, na=False)].copy()
    result = result.reset_index(drop=True)
    if "rank" in result.columns:
        result["rank"] = range(1, len(result) + 1)
    return result


def _ranked(
    frame: DataFrame,
    *,
    screen_type: str,
    by: list[str],
    ascending: list[bool],
    top_n: int,
) -> DataFrame:
    ranked = frame.sort_values(by, ascending=ascending, na_position="last").head(top_n).copy()
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    ranked.insert(0, "screen_type", screen_type)
    return ranked.reset_index(drop=True)


def _ema_similarity(
    snapshot: DataFrame,
    comparison_ticker: str | None,
    top_n: int,
    *,
    min_similarity: float,
    gap_tolerance: float,
) -> DataFrame:
    metric_columns = {
        "ema_array_signature": "object",
        "ema_exact_array_match": "int64",
        "ema_order_similarity_pct": "float64",
        "ema_shape_distance_pct": "float64",
        "ema_mean_gap_difference_pct": "float64",
        "ema_max_gap_difference_pct": "float64",
    }
    if comparison_ticker is None:
        empty = snapshot.head(0).copy()
        for column, dtype in metric_columns.items():
            empty[column] = pd.Series(dtype=dtype)
        empty["ema_distance_pct"] = pd.Series(dtype="float64")
        empty["ema_similarity_score"] = pd.Series(dtype="float64")
        empty["alignment_match"] = pd.Series(dtype="int64")
        return _ranked(
            empty,
            screen_type="ema_similarity",
            by=[
                "ema_exact_array_match",
                "ema_order_similarity_pct",
                "ema_max_gap_difference_pct",
                "ema_shape_distance_pct",
                "ticker",
            ],
            ascending=[False, False, True, True, True],
            top_n=top_n,
        )
    ema_columns = [f"ema_{window}" for window in EMA_WINDOWS]
    valid = snapshot.loc[
        snapshot[ema_columns].notna().all(axis=1)
        & snapshot["close"].gt(0)
        & snapshot[ema_columns].gt(0).all(axis=1)
        & snapshot["history_ready_448"].eq(1)
    ].copy()
    target = valid.loc[valid["ticker"].eq(comparison_ticker)]
    if target.empty:
        raise ValueError(
            f"Comparison ticker {comparison_ticker} has no same-date 448-day-ready indicators"
        )

    metrics = calculate_ema_similarity_metrics(
        valid,
        reference_index=target.index[0],
    )
    valid = valid.join(metrics)
    # Retain the original storage columns while giving them V140 semantics.
    valid["ema_distance_pct"] = valid["ema_shape_distance_pct"]
    valid["ema_similarity_score"] = valid["ema_order_similarity_pct"]
    target_alignment = str(target.iloc[0]["ema_alignment"])
    valid["alignment_match"] = valid["ema_alignment"].eq(target_alignment).astype("int64")
    valid = valid.loc[
        ~valid["ticker"].eq(comparison_ticker)
        & valid["ema_order_similarity_pct"].ge(min_similarity - 1e-12)
        & valid["ema_max_gap_difference_pct"].le(gap_tolerance + 1e-12)
    ]
    return _ranked(
        valid,
        screen_type="ema_similarity",
        by=[
            "ema_exact_array_match",
            "ema_order_similarity_pct",
            "ema_max_gap_difference_pct",
            "ema_shape_distance_pct",
            "name",
            "ticker",
        ],
        ascending=[False, False, True, True, True, True],
        top_n=top_n,
    )


def build_market_screens(
    snapshot: DataFrame,
    *,
    as_of_date: dt.date,
    comparison_ticker: object | None = "222800",
    top_n: int = 50,
    ema_min_similarity: float = EMA_DEFAULT_MIN_SIMILARITY,
    ema_gap_tolerance: float = EMA_DEFAULT_GAP_TOLERANCE,
) -> ScreeningResult:
    """Build the four fixed screens from one local same-date snapshot."""

    if snapshot.empty:
        raise ValueError(f"No technical-indicator rows are available for {as_of_date}")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    min_similarity, gap_tolerance = validate_ema_similarity_options(
        ema_min_similarity,
        ema_gap_tolerance,
    )
    required = {
        "ticker",
        "trade_date",
        "close",
        "estimated_trading_value",
        "daily_return_pct",
        "history_ready_448",
        "is_52w_high",
        "is_52w_breakout",
        "ema_alignment",
        "weekly_return_pct",
        "is_bb_upper_breakout",
        "formula_version",
        *(f"ema_{window}" for window in EMA_WINDOWS),
    }
    if missing := required.difference(snapshot.columns):
        raise ValueError(f"Screen snapshot missing columns: {sorted(missing)}")
    if snapshot["ticker"].duplicated().any():
        raise ValueError("Screen snapshot contains duplicate tickers")
    dates = pd.to_datetime(snapshot["trade_date"]).dt.date.unique().tolist()
    if dates != [as_of_date]:
        raise ValueError(f"Screen snapshot is not limited to {as_of_date}: {dates}")
    formula_versions = set(snapshot["formula_version"].dropna().astype("int64"))
    if formula_versions != {FORMULA_VERSION}:
        raise ValueError(
            f"Expected indicator formula version {FORMULA_VERSION}, received "
            f"{sorted(formula_versions)}"
        )

    comparison = None if comparison_ticker is None else normalize_ticker(comparison_ticker)
    universe = exclude_spac_securities(snapshot)
    universe["formula_version"] = FORMULA_VERSION

    ema = _ema_similarity(
        universe,
        comparison,
        top_n,
        min_similarity=min_similarity,
        gap_tolerance=gap_tolerance,
    )

    # "당일 52주 신고가" means today's high strictly exceeded the highest
    # comparable high from the preceding 252 sessions.  A stock that merely
    # remains equal to an earlier 52-week high is not a new breakout today.
    highs = universe.loc[universe["is_52w_breakout"].eq(1)].copy()
    highs = _ranked(
        highs,
        screen_type="high_52w",
        by=["daily_return_pct", "ticker"],
        ascending=[False, True],
        top_n=top_n,
    )

    bollinger = universe.loc[universe["is_bb_upper_breakout"].eq(1)].copy()
    bollinger = _ranked(
        bollinger,
        screen_type="bollinger_breakout",
        by=["weekly_return_pct", "estimated_trading_value", "ticker"],
        ascending=[False, False, True],
        top_n=top_n,
    )

    weekly = universe.loc[universe["weekly_return_pct"].notna()].copy()
    weekly = _ranked(
        weekly,
        screen_type="weekly_return",
        by=["weekly_return_pct", "estimated_trading_value", "ticker"],
        ascending=[False, False, True],
        top_n=top_n,
    )

    return ScreeningResult(
        as_of_date=as_of_date,
        comparison_ticker=comparison,
        universe_count=len(universe),
        ema_similarity=ema,
        high_52w=highs,
        bollinger_breakout=bollinger,
        weekly_return=weekly,
    )
