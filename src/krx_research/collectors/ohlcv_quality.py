"""Auditable handling of adjusted-price bounds and invalid provider rows.

Only the named Naver routes may receive a minimal envelope adjustment.  A
one-KRW mismatch retains the original policy.  Larger adjusted-price rounding
mismatches are accepted only when they fit inside one conservative legacy KRX
price tick.  For prices below KRW 1,000, an independently rounded adjusted
OHLC envelope may instead differ by at most ten won; that narrower special
case also requires a relative discrepancy no greater than 1.0%.  This is a
normalization policy, not a claim to have recovered an exchange print.
No-trade placeholders remain in the audit and outside the trading-day series.
An explicit recovery mode can additionally quarantine non-positive source rows
and minimally expand an inconsistent adjusted OHLC envelope.  A small reviewed
ticker list permits larger *counts* of those same bounded actions when the
public date-range source has a known, repeatable legacy pattern.  Recovery never
changes open, close, or volume, and the normal collection route remains strict.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from .common import MarketDataError, _retrieved_at

QUALITY_POLICY_VERSION = 5
RECOVERY_QUALITY_POLICY_VERSION = 7
TICK_QUALITY_POLICY_VERSION = 2
LEGACY_QUALITY_POLICY_VERSION = 1
SUB_1000_ROUNDING_ABSOLUTE_LIMIT = 10
SUB_1000_ROUNDING_RELATIVE_LIMIT_PCT = 1.0
RECOVERY_ENVELOPE_RELATIVE_LIMIT_PCT = 25.0
RECOVERY_MAX_EXCEPTION_RATIO = 0.10
RECOVERY_MIN_EXCEPTION_ROWS = 25
PRICE_COLUMNS = ["open", "high", "low", "close"]
VALUE_COLUMNS = [*PRICE_COLUMNS, "volume"]
NAVER_ADJUSTED_SOURCES = {
    "pykrx:NAVER_ADJUSTED",
    "FinanceDataReader:NAVER_ADJUSTED",
    "NAVER:DATE_RANGE_ADJUSTED",
}
NAVER_DATE_RANGE_SOURCE = "NAVER:DATE_RANGE_ADJUSTED"

# Reviewed against the complete public date-range response on 2026-09-07.
# These ceilings bound the total observations seen in the requested 30-year
# range; normalize_ohlcv receives at most one five-year window at a time.
REVIEWED_BULK_PROVIDER_ENVELOPE_LIMITS = {
    "001065": 410,
    "006345": 247,
    "006730": 741,
    "014100": 669,
    "019175": 407,
    "036170": 335,
    "054180": 164,
}
REVIEWED_BULK_LOW_ZERO_LIMITS = {
    "001840": 1_166,
    "010170": 1_166,
    "025320": 1_166,
    "036810": 231,
}


def _legacy_krx_tick_limit(price: pd.Series) -> pd.Series:
    """Return a conservative one-tick ceiling for integral adjusted prices.

    Historic back-adjustment can turn an original exchange tick into several
    won on the current price basis.  The legacy KRX bands are never wider than
    roughly 0.5% at a boundary (one won below KRW 1,000), so they repair small
    rounding envelopes while still rejecting material source corruption.
    """

    values = price.astype(float).to_numpy()
    limits = np.select(
        [
            values < 1_000,
            values < 5_000,
            values < 10_000,
            values < 50_000,
            values < 100_000,
            values < 500_000,
        ],
        [1, 5, 10, 50, 100, 500],
        default=1_000,
    )
    return pd.Series(limits, index=price.index, dtype="float64")


def normalize_ohlcv(
    frame: DataFrame,
    source: str,
    ticker: str,
    *,
    source_url: str = "",
    recovery_mode: bool = False,
) -> DataFrame:
    if frame.empty:
        raise MarketDataError(f"{source} returned no OHLCV rows for {ticker}.")
    work = frame.copy().rename(
        columns={
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
            "등락률": "change_ratio",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Change": "change_ratio",
        }
    )
    if work.columns.duplicated().any():
        raise MarketDataError(f"{source} returned duplicate OHLCV columns.")
    if missing := set(VALUE_COLUMNS).difference(work.columns):
        raise MarketDataError(f"{source} OHLCV missing columns: {sorted(missing)}")
    work.index = pd.DatetimeIndex(pd.to_datetime(work.index)).tz_localize(None).normalize()
    work.index.name = "date"
    work = work.sort_index()
    if work.index.hasnans or work.index.duplicated().any():
        raise MarketDataError(f"{source} returned missing or duplicate OHLCV dates for {ticker}.")
    for column in VALUE_COLUMNS:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if not np.isfinite(work[VALUE_COLUMNS].to_numpy(dtype=float)).all():
        raise MarketDataError(f"{source} returned non-finite/non-numeric OHLCV values.")
    if ((work["volume"] < 0) | (work["volume"] % 1 != 0)).any():
        raise MarketDataError(f"{source} returned negative or fractional volume.")

    raw = work[VALUE_COLUMNS].copy()
    eligible_source = source in NAVER_ADJUSTED_SOURCES
    if recovery_mode and not eligible_source:
        raise MarketDataError(
            f"Recovery normalization is not permitted for source {source}."
        )
    no_trade = (
        (
            (work[["open", "high", "low"]] == 0).all(axis=1)
            & (work["close"] > 0)
            & (work["volume"] == 0)
        )
        if eligible_source
        else pd.Series(False, index=work.index)
    )
    trading = ~no_trade
    nonpositive = trading & (work[PRICE_COLUMNS] <= 0).any(axis=1)
    reviewed_low_zero = (
        nonpositive
        & (source == NAVER_DATE_RANGE_SOURCE)
        & (str(ticker) in REVIEWED_BULK_LOW_ZERO_LIMITS)
        & (work["low"] == 0)
        & (work[["open", "high", "close"]] > 0).all(axis=1)
        & (work[PRICE_COLUMNS] % 1 == 0).all(axis=1)
    )
    if nonpositive.any() and not recovery_mode:
        raise MarketDataError(f"{source} returned non-positive trading prices.")
    if nonpositive.any():
        exception_limit = max(
            RECOVERY_MIN_EXCEPTION_ROWS,
            int(np.ceil(len(work) * RECOVERY_MAX_EXCEPTION_RATIO)),
        )
        nonpositive_count = int(nonpositive.sum())
        if nonpositive_count > exception_limit:
            reviewed_limit = REVIEWED_BULK_LOW_ZERO_LIMITS.get(str(ticker), 0)
            reviewed_exception = (
                source == NAVER_DATE_RANGE_SOURCE
                and bool(reviewed_low_zero.loc[nonpositive].all())
                and nonpositive_count <= reviewed_limit
            )
            if not reviewed_exception:
                raise MarketDataError(
                    f"{source} recovery non-positive row limit exceeded: "
                    f"rows={nonpositive_count}, limit={exception_limit}"
                )
        trading &= ~nonpositive
        if not trading.any():
            raise MarketDataError(
                f"{source} recovery excluded every trading row for {ticker}."
            )

    envelope_high = work[PRICE_COLUMNS].max(axis=1)
    envelope_low = work[PRICE_COLUMNS].min(axis=1)
    high_delta = envelope_high - work["high"]
    low_delta = work["low"] - envelope_low
    invalid = trading & ((high_delta > 0) | (low_delta > 0))
    integral_prices = (work[PRICE_COLUMNS] % 1 == 0).all(axis=1)
    structurally_repairable = (
        invalid
        & eligible_source
        & (work["low"] <= work["high"])
        & integral_prices
    )
    one_krw = (
        structurally_repairable
        & (high_delta <= 1)
        & (low_delta <= 1)
    )
    tick_limit = _legacy_krx_tick_limit(envelope_high)
    one_tick = (
        structurally_repairable
        & ~one_krw
        & (high_delta <= tick_limit)
        & (low_delta <= tick_limit)
    )
    max_delta = pd.concat([high_delta, low_delta], axis=1).max(axis=1)
    relative_delta_pct = max_delta / envelope_low.where(trading) * 100
    sub_1000_rounding = (
        structurally_repairable
        & ~one_krw
        & ~one_tick
        & (envelope_high < 1_000)
        & (max_delta <= SUB_1000_ROUNDING_ABSOLUTE_LIMIT)
        & (relative_delta_pct <= SUB_1000_ROUNDING_RELATIVE_LIMIT_PCT)
    )
    normal_repairable = one_krw | one_tick | sub_1000_rounding
    recovery_relative_delta_pct = max_delta / envelope_high.where(trading) * 100
    provider_envelope = (
        structurally_repairable
        & ~normal_repairable
        & recovery_mode
        & (recovery_relative_delta_pct <= RECOVERY_ENVELOPE_RELATIVE_LIMIT_PCT)
    )
    reviewed_provider_envelope = (
        provider_envelope
        & (source == NAVER_DATE_RANGE_SOURCE)
        & (str(ticker) in REVIEWED_BULK_PROVIDER_ENVELOPE_LIMITS)
    )
    if provider_envelope.any():
        exception_limit = max(
            RECOVERY_MIN_EXCEPTION_ROWS,
            int(np.ceil(len(work) * RECOVERY_MAX_EXCEPTION_RATIO)),
        )
        provider_envelope_count = int(provider_envelope.sum())
        if provider_envelope_count > exception_limit:
            reviewed_limit = REVIEWED_BULK_PROVIDER_ENVELOPE_LIMITS.get(
                str(ticker), 0
            )
            reviewed_exception = (
                source == NAVER_DATE_RANGE_SOURCE
                and bool(reviewed_provider_envelope.loc[provider_envelope].all())
                and provider_envelope_count <= reviewed_limit
            )
            if not reviewed_exception:
                raise MarketDataError(
                    f"{source} recovery envelope row limit exceeded: "
                    f"rows={provider_envelope_count}, limit={exception_limit}"
                )
    repairable = normal_repairable | provider_envelope
    unrepairable = invalid & ~repairable
    if unrepairable.any():
        samples = []
        for date in work.index[unrepairable][:5]:
            samples.append(
                {
                    "date": date.date().isoformat(),
                    "open": float(raw.at[date, "open"]),
                    "high": float(raw.at[date, "high"]),
                    "low": float(raw.at[date, "low"]),
                    "close": float(raw.at[date, "close"]),
                    "high_delta": float(high_delta.at[date]),
                    "low_delta": float(low_delta.at[date]),
                    "tick_limit": float(tick_limit.at[date]),
                    "relative_delta_pct": float(relative_delta_pct.at[date]),
                    "sub_1000_absolute_limit": SUB_1000_ROUNDING_ABSOLUTE_LIMIT,
                    "sub_1000_relative_limit_pct": (
                        SUB_1000_ROUNDING_RELATIVE_LIMIT_PCT
                    ),
                    "recovery_mode": recovery_mode,
                    "recovery_relative_delta_pct": float(
                        recovery_relative_delta_pct.at[date]
                    ),
                    "recovery_relative_limit_pct": (
                        RECOVERY_ENVELOPE_RELATIVE_LIMIT_PCT
                    ),
                }
            )
        raise MarketDataError(
            f"{source} returned OHLCV rows outside audited rounding limits: "
            f"{samples}"
        )
    work.loc[repairable, "high"] = envelope_high.loc[repairable]
    work.loc[repairable, "low"] = envelope_low.loc[repairable]

    retrieved_at = _retrieved_at()
    events: list[dict[str, object]] = []
    for date in work.index[no_trade | nonpositive | repairable]:
        is_placeholder = bool(no_trade.loc[date])
        is_nonpositive = bool(nonpositive.loc[date])
        is_one_tick = bool(one_tick.loc[date])
        is_sub_1000_rounding = bool(sub_1000_rounding.loc[date])
        is_provider_envelope = bool(provider_envelope.loc[date])
        if is_placeholder:
            action = "no_trade_placeholder"
            policy_version = LEGACY_QUALITY_POLICY_VERSION
        elif is_nonpositive:
            action = "nonpositive_price_row_excluded"
            policy_version = RECOVERY_QUALITY_POLICY_VERSION
        elif is_provider_envelope:
            action = "bounds_adjusted_provider_envelope"
            policy_version = RECOVERY_QUALITY_POLICY_VERSION
        elif is_sub_1000_rounding:
            action = "bounds_adjusted_sub1000_rounding"
            policy_version = QUALITY_POLICY_VERSION
        elif is_one_tick:
            action = "bounds_adjusted_tick"
            policy_version = TICK_QUALITY_POLICY_VERSION
        else:
            action = "bounds_adjusted_1krw"
            policy_version = LEGACY_QUALITY_POLICY_VERSION
        events.append(
            {
                "ticker": ticker,
                "trade_date": date.date().isoformat(),
                "source": source,
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "policy_version": policy_version,
                "action": action,
                "raw": {column: float(raw.at[date, column]) for column in VALUE_COLUMNS},
                "normalized": None
                if is_placeholder or is_nonpositive
                else {column: float(work.at[date, column]) for column in VALUE_COLUMNS},
            }
        )

    result = work.loc[trading].copy()
    # FDR Change is a ratio; pykrx 등락률 is a percentage. Keep one unit in PostgreSQL.
    if "change_ratio" in result:
        result["change_ratio"] = pd.to_numeric(result["change_ratio"], errors="coerce")
        if "Change" in frame.columns:
            result["change_ratio"] *= 100
        result["change_ratio"] = result["change_ratio"].replace([np.inf, -np.inf], np.nan)
    result["ticker"] = ticker
    result["source"] = source
    result["source_url"] = source_url
    result["adjusted"] = True
    result["retrieved_at"] = retrieved_at
    quality_summary: dict[str, object] = {
        "policy_version": QUALITY_POLICY_VERSION,
        "bounds_adjusted_rows": int(repairable.sum()),
        "bounds_adjusted_1krw_rows": int(one_krw.sum()),
        "bounds_adjusted_tick_rows": int(one_tick.sum()),
        "bounds_adjusted_sub1000_rounding_rows": int(
            sub_1000_rounding.sum()
        ),
        "no_trade_rows": int(no_trade.sum()),
    }
    quality_limit_reasons: list[str] = []
    if recovery_mode:
        quality_summary.update(
            {
                "policy_version": RECOVERY_QUALITY_POLICY_VERSION,
                "bounds_adjusted_provider_envelope_rows": int(
                    provider_envelope.sum()
                ),
                "nonpositive_price_rows": int(nonpositive.sum()),
                "reviewed_bulk_provider_envelope_rows": int(
                    reviewed_provider_envelope.sum()
                ),
                "reviewed_bulk_low_zero_rows": int(reviewed_low_zero.sum()),
                "recovery_mode": True,
            }
        )
        if (provider_envelope & ~reviewed_provider_envelope).any():
            quality_limit_reasons.append("provider_envelope_repaired")
        if reviewed_provider_envelope.any():
            quality_limit_reasons.append(
                "reviewed_bulk_provider_envelope_repaired"
            )
        if (nonpositive & ~reviewed_low_zero).any():
            quality_limit_reasons.append("nonpositive_price_rows_excluded")
        if reviewed_low_zero.any():
            quality_limit_reasons.append("reviewed_bulk_low_zero_rows_excluded")

    result.attrs = {
        "ticker": ticker,
        "source": source,
        "source_url": source_url,
        "raw_rows": len(raw),
        "quality_events": events,
        "quality_summary": quality_summary,
        "quality_limit_reasons": quality_limit_reasons,
        "recovery_mode": recovery_mode,
    }
    return result
