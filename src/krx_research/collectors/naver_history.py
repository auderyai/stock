"""Date-bounded public Naver chart requests for long history.

No login or installed-package modification is used. The router must compare
overlapping closes with an existing adjusted provider before using this data.
"""

from __future__ import annotations

import ast
import datetime as dt
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlencode

import pandas as pd
from pandas import DataFrame

from .common import MarketDataError, normalize_date, normalize_ticker
from .history_coverage import assess_ohlcv_coverage, require_ohlcv_coverage
from .ohlcv_quality import (
    QUALITY_POLICY_VERSION,
    RECOVERY_QUALITY_POLICY_VERSION,
    normalize_ohlcv,
)

DATE_RANGE_URL = "https://api.finance.naver.com/siseJson.naver"
DATE_RANGE_SOURCE = "NAVER:DATE_RANGE_ADJUSTED"


def history_windows(start: object, end: object) -> Iterator[tuple[dt.date, dt.date]]:
    current = normalize_date(start)
    last = normalize_date(end)
    if current > last:
        raise ValueError("start must not be later than end")
    while current <= last:
        limit = (pd.Timestamp(current) + pd.DateOffset(years=5)).date() - dt.timedelta(days=1)
        window_end = min(limit, last)
        yield current, window_end
        current = window_end + dt.timedelta(days=1)


def parse_naver_history(text: str) -> DataFrame:
    if len(text) > 4_000_000:
        raise MarketDataError("Naver date-range response is unexpectedly large")
    try:
        # Naver uses a single-quoted header: this is not strict JSON. Never use eval.
        rows = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError, RecursionError) as error:
        raise MarketDataError("Invalid Naver date-range response") from error
    expected = ["날짜", "시가", "고가", "저가", "종가", "거래량"]
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        raise MarketDataError("Missing Naver date-range header")
    header = rows[0]
    if header[:6] != expected or len(set(header)) != len(header):
        raise MarketDataError("Unexpected Naver date-range columns")
    # Older dates can omit optional columns such as 외국인소진율 even though the
    # header still names them. OHLCV is always the first six fields, so validate
    # and retain exactly those fields instead of padding unrelated metadata.
    price_rows: list[list[object]] = []
    malformed: list[str] = []
    for position, row in enumerate(rows[1:], start=1):
        if not isinstance(row, list):
            malformed.append(f"row={position}:type={type(row).__name__}")
        elif not 6 <= len(row) <= len(header):
            malformed.append(f"row={position}:columns={len(row)}")
        else:
            price_rows.append(row[:6])
    if malformed:
        details = ", ".join(malformed[:5])
        raise MarketDataError(
            f"Malformed Naver date-range rows ({details}; header_columns={len(header)})"
        )
    frame = DataFrame(price_rows, columns=expected)
    try:
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("날짜"), format="%Y%m%d"))
    except (TypeError, ValueError) as error:
        raise MarketDataError("Invalid Naver date-range date") from error
    return frame


def fetch_naver_date_range_ohlcv(
    ticker: str,
    start: object,
    end: object,
    *,
    get: Callable[..., object] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    recovery_mode: bool = False,
) -> DataFrame:
    if get is None:
        import requests

        get = requests.get
    code = normalize_ticker(ticker)
    frames: list[DataFrame] = []
    events: list[dict[str, object]] = []
    urls: list[str] = []
    raw_rows = 0
    bounds_adjusted = 0
    bounds_adjusted_1krw = 0
    bounds_adjusted_tick = 0
    bounds_adjusted_sub1000_rounding = 0
    bounds_adjusted_provider_envelope = 0
    nonpositive_price_rows = 0
    reviewed_bulk_provider_envelope_rows = 0
    reviewed_bulk_low_zero_rows = 0
    no_trade = 0
    source_history_start: dt.date | None = None
    leading_empty_windows: list[dict[str, str]] = []
    internal_empty_windows: list[dict[str, str]] = []
    incomplete_windows: list[dict[str, object]] = []
    quality_limit_reasons: set[str] = set()
    for position, (window_start, window_end) in enumerate(history_windows(start, end)):
        if position:
            sleeper(0.25)
        params = {
            "symbol": code,
            "requestType": "1",
            "timeframe": "day",
            "startTime": window_start.strftime("%Y%m%d"),
            "endTime": window_end.strftime("%Y%m%d"),
        }
        response = get(DATE_RANGE_URL, params=params, timeout=(5, 30))
        response.raise_for_status()
        url = DATE_RANGE_URL + "?" + urlencode(params)
        urls.append(url)
        raw = parse_naver_history(response.text)
        if raw.empty:
            # A final short window can contain only a weekend/holiday. A whole
            # missing historical window must never disappear from the result.
            if (window_end - window_start).days <= 10:
                continue
            if not frames:
                leading_empty_windows.append(
                    {"start": window_start.isoformat(), "end": window_end.isoformat()}
                )
                continue
            if recovery_mode:
                internal_empty_windows.append(
                    {"start": window_start.isoformat(), "end": window_end.isoformat()}
                )
                quality_limit_reasons.add("provider_history_gaps")
                continue
            raise MarketDataError(
                f"No Naver rows after series start for {code}: "
                f"{window_start}..{window_end}"
            )
        frame = normalize_ohlcv(
            raw,
            DATE_RANGE_SOURCE,
            code,
            source_url=url,
            recovery_mode=recovery_mode,
        )
        first_observation = raw.index.min().date()
        coverage_start = window_start
        if not frames and (
            leading_empty_windows
            or (first_observation - window_start).days > 10
        ):
            source_history_start = first_observation
            coverage_start = first_observation
        window_coverage = assess_ohlcv_coverage(
            frame,
            coverage_start,
            window_end,
        )
        if window_coverage["status"] == "incomplete" and recovery_mode:
            incomplete_windows.append(
                {
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                    "actual_start": window_coverage["actual_start"],
                    "actual_end": window_coverage["actual_end"],
                    "issues": window_coverage["issues"],
                }
            )
            quality_limit_reasons.add("provider_history_gaps")
        else:
            require_ohlcv_coverage(
                frame,
                coverage_start,
                window_end,
                allow_quality_limit=recovery_mode,
            )
        events.extend(frame.attrs["quality_events"])
        quality_limit_reasons.update(frame.attrs.get("quality_limit_reasons", []))
        raw_rows += frame.attrs["raw_rows"]
        bounds_adjusted += frame.attrs["quality_summary"]["bounds_adjusted_rows"]
        bounds_adjusted_1krw += frame.attrs["quality_summary"][
            "bounds_adjusted_1krw_rows"
        ]
        bounds_adjusted_tick += frame.attrs["quality_summary"][
            "bounds_adjusted_tick_rows"
        ]
        bounds_adjusted_sub1000_rounding += frame.attrs["quality_summary"][
            "bounds_adjusted_sub1000_rounding_rows"
        ]
        bounds_adjusted_provider_envelope += int(
            frame.attrs["quality_summary"].get(
                "bounds_adjusted_provider_envelope_rows", 0
            )
        )
        nonpositive_price_rows += int(
            frame.attrs["quality_summary"].get("nonpositive_price_rows", 0)
        )
        reviewed_bulk_provider_envelope_rows += int(
            frame.attrs["quality_summary"].get(
                "reviewed_bulk_provider_envelope_rows", 0
            )
        )
        reviewed_bulk_low_zero_rows += int(
            frame.attrs["quality_summary"].get(
                "reviewed_bulk_low_zero_rows", 0
            )
        )
        no_trade += frame.attrs["quality_summary"]["no_trade_rows"]
        frame.attrs = {}
        frames.append(frame)
    if not frames:
        raise MarketDataError(f"No date-range history for {code}")
    combined = pd.concat(frames).sort_index()
    if combined.index.duplicated().any():
        raise MarketDataError("Overlapping/duplicate Naver date-range rows")
    combined["change_ratio"] = combined["close"].pct_change(fill_method=None) * 100
    combined.attrs = {
        "ticker": code,
        "source": DATE_RANGE_SOURCE,
        "source_url": DATE_RANGE_URL,
        "request_urls": urls,
        "leading_empty_windows": leading_empty_windows,
        "internal_empty_windows": internal_empty_windows,
        "incomplete_windows": incomplete_windows,
        "source_history_start": (
            source_history_start.isoformat() if source_history_start else None
        ),
        "raw_rows": raw_rows,
        "quality_events": events,
        "quality_summary": {
            "policy_version": (
                RECOVERY_QUALITY_POLICY_VERSION
                if recovery_mode
                else QUALITY_POLICY_VERSION
            ),
            "bounds_adjusted_rows": bounds_adjusted,
            "bounds_adjusted_1krw_rows": bounds_adjusted_1krw,
            "bounds_adjusted_tick_rows": bounds_adjusted_tick,
            "bounds_adjusted_sub1000_rounding_rows": (
                bounds_adjusted_sub1000_rounding
            ),
            "bounds_adjusted_provider_envelope_rows": (
                bounds_adjusted_provider_envelope
            ),
            "nonpositive_price_rows": nonpositive_price_rows,
            "reviewed_bulk_provider_envelope_rows": (
                reviewed_bulk_provider_envelope_rows
            ),
            "reviewed_bulk_low_zero_rows": reviewed_bulk_low_zero_rows,
            "no_trade_rows": no_trade,
            "recovery_mode": recovery_mode,
        },
        "quality_limit_reasons": sorted(quality_limit_reasons),
        "recovery_mode": recovery_mode,
        "adjusted_basis_verified": False,
    }
    require_ohlcv_coverage(
        combined,
        source_history_start or start,
        end,
        allow_quality_limit=recovery_mode,
    )
    return combined


def verify_adjusted_overlap(reference: DataFrame, candidate: DataFrame) -> int:
    common = reference.index.intersection(candidate.index)
    required_rows = min(20, len(reference), len(candidate))
    if required_rows == 0 or len(common) < required_rows:
        raise MarketDataError(
            "Insufficient overlapping closes to verify the date-range price basis"
        )
    left = reference.loc[common, "close"].astype(float)
    right = candidate.loc[common, "close"].astype(float)
    different = left != right
    if different.any():
        dates = common[different].strftime("%Y-%m-%d").tolist()
        raise MarketDataError(f"Date-range adjusted-close mismatch: {dates[:10]}")
    candidate.attrs["adjusted_basis_verified"] = True
    candidate.attrs["adjusted_overlap_rows"] = len(common)
    return len(common)
