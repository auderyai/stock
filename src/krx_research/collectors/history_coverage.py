"""Conservative history checks; these do not replace a KRX trading calendar."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from pandas import DataFrame

from .common import MarketDataError, normalize_date

COVERAGE_CHECK_VERSION = 1
BOUNDARY_TOLERANCE_DAYS = 10
MAX_UNEXPLAINED_GAP_DAYS = 14
FULL_COVERAGE_STATUS = "bounds_checked"
SOURCE_LIMITED_STATUS = "source_limited"
QUALITY_LIMITED_STATUS = "quality_limited"
QUALITY_LIMITED_ISSUES = {
    "missing_early_history",
    "missing_recent_history",
    "unexplained_internal_gap",
}


class OhlcvCoverageError(MarketDataError):
    """The response does not establish the requested history coverage."""

    def __init__(self, coverage: dict[str, object], message: str | None = None) -> None:
        self.coverage = coverage
        super().__init__(
            message
            or (
                f"Incomplete OHLCV history: requested={coverage['requested_start']}.."
                f"{coverage['requested_end']}, received={coverage['actual_start']}.."
                f"{coverage['actual_end']}, rows={coverage['raw_rows']}; "
                f"issues={coverage['issues']}"
            )
        )


def effective_history_start(start: object, listing_date: object | None = None) -> dt.date:
    requested = normalize_date(start)
    if listing_date is None or pd.isna(listing_date) or str(listing_date).strip() == "":
        return requested
    return max(requested, normalize_date(listing_date))


def coverage_establishes_requested_end(
    coverage: dict[str, object],
    required_end: object | None = None,
) -> bool:
    """Return whether a checkpoint proves the requested tail is complete.

    A weekday request whose provider response stops before that date remains
    provisional. This deliberately does not guess Korean weekday holidays;
    rechecking is safer than permanently skipping a newly published daily bar.
    Weekend endpoints may resolve to the preceding trading day.
    """

    endpoint = coverage["requested_end"] if required_end is None else required_end
    requested_end = normalize_date(endpoint)  # type: ignore[arg-type]
    actual_end_value = coverage.get("actual_end")
    if actual_end_value is None:
        return False
    actual_end = normalize_date(actual_end_value)  # type: ignore[arg-type]
    return actual_end >= requested_end or requested_end.weekday() >= 5


def assess_ohlcv_coverage(
    frame: DataFrame,
    start: object,
    end: object,
    *,
    listing_date: object | None = None,
    source_history_start: object | None = None,
) -> dict[str, object]:
    requested_start = normalize_date(start)
    requested_end = normalize_date(end)
    expected_start = effective_history_start(start, listing_date)
    if requested_start > requested_end:
        raise ValueError("start must not be later than end")
    if expected_start > requested_end:
        raise ValueError("The requested range ends before this security was listed")

    if "trade_date" in frame:
        trading_dates = pd.DatetimeIndex(pd.to_datetime(frame["trade_date"]))
    else:
        trading_dates = pd.DatetimeIndex(pd.to_datetime(frame.index))
    trading_dates = trading_dates.tz_localize(None).normalize().sort_values().unique()
    valid_trading_dates = trading_dates.dropna()
    trading_first = valid_trading_dates.min().date() if len(valid_trading_dates) else None
    trading_last = valid_trading_dates.max().date() if len(valid_trading_dates) else None
    excluded_dates = [
        event["trade_date"]
        for event in frame.attrs.get("quality_events", [])
        if event["action"] in {"no_trade_placeholder", "nonpositive_price_row_excluded"}
    ]
    dates = trading_dates.append(pd.DatetimeIndex(pd.to_datetime(excluded_dates)))
    dates = dates.tz_localize(None).normalize().sort_values().unique()
    issues: list[str] = []
    if dates.hasnans:
        issues.append("missing_date")
        dates = dates.dropna()
    first = dates.min().date() if len(dates) else None
    last = dates.max().date() if len(dates) else None
    max_gap = int(pd.Series(dates).diff().dt.days.max()) if len(dates) > 1 else 0
    if first is None:
        issues.append("empty_response")
    else:
        if first < expected_start or last > requested_end:
            issues.append("out_of_requested_range")
        if (first - expected_start).days > BOUNDARY_TOLERANCE_DAYS:
            issues.append("missing_early_history")
        if (requested_end - last).days > BOUNDARY_TOLERANCE_DAYS:
            issues.append("missing_recent_history")
        if max_gap > MAX_UNEXPLAINED_GAP_DAYS:
            issues.append("unexplained_internal_gap")
    source_start = None
    if source_history_start is not None:
        source_start = normalize_date(source_history_start)
        if source_start < expected_start or source_start > requested_end:
            issues.append("invalid_source_history_start")
        elif first is None or first != source_start:
            issues.append("unverified_source_history_start")

    source_limited = (
        source_start is not None
        and source_start > expected_start
        and set(issues) == {"missing_early_history"}
    )
    quality_limit_reasons = sorted(
        {str(reason) for reason in frame.attrs.get("quality_limit_reasons", [])}
    )
    quality_limited = bool(quality_limit_reasons) and set(issues).issubset(QUALITY_LIMITED_ISSUES)
    if not issues and not quality_limited:
        status = FULL_COVERAGE_STATUS
    elif quality_limited:
        status = QUALITY_LIMITED_STATUS
    elif source_limited:
        status = SOURCE_LIMITED_STATUS
    else:
        status = "incomplete"
    end_is_provisional = last is None or (last < requested_end and requested_end.weekday() < 5)
    return {
        "check_version": COVERAGE_CHECK_VERSION,
        "status": status,
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "effective_start": expected_start.isoformat(),
        "actual_start": first.isoformat() if first else None,
        "actual_end": last.isoformat() if last else None,
        "end_is_provisional": end_is_provisional,
        "trading_start": trading_first.isoformat() if trading_first else None,
        "trading_end": trading_last.isoformat() if trading_last else None,
        "raw_rows": len(dates),
        "trading_rows": len(frame),
        "boundary_tolerance_days": BOUNDARY_TOLERANCE_DAYS,
        "max_observed_gap_days": max_gap,
        "issues": issues,
        "source_history_start": source_start.isoformat() if source_start else None,
        "source_limit_days": ((source_start - expected_start).days if source_limited else 0),
        "source_limit_reason": (
            "provider_series_starts_after_effective_start" if source_limited else None
        ),
        "quality_limit_reasons": quality_limit_reasons,
        "calendar_verified": False,
    }


def require_ohlcv_coverage(
    frame: DataFrame,
    start: object,
    end: object,
    *,
    listing_date: object | None = None,
    source_history_start: object | None = None,
    allow_source_limit: bool = False,
    allow_quality_limit: bool = False,
) -> dict[str, object]:
    coverage = assess_ohlcv_coverage(
        frame,
        start,
        end,
        listing_date=listing_date,
        source_history_start=source_history_start,
    )
    frame.attrs["coverage"] = coverage
    accepted = (
        coverage["status"] == FULL_COVERAGE_STATUS
        or (allow_source_limit and coverage["status"] == SOURCE_LIMITED_STATUS)
        or (allow_quality_limit and coverage["status"] == QUALITY_LIMITED_STATUS)
    )
    if not accepted:
        raise OhlcvCoverageError(coverage)
    return coverage
