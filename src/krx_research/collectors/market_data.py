"""Login-free KRX market-data routing with explicit source provenance.

The project intentionally does not create or use KRX_ID/KRX_PW credentials.
FinanceDataReader supplies the cached KRX security master, while pykrx is used
only for its adjusted per-security OHLCV route backed by Naver Finance.
"""

from __future__ import annotations

import datetime as dt
import warnings
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
from pandas import DataFrame

from .common import MarketDataError, _retrieved_at, normalize_date, normalize_ticker
from .history_coverage import OhlcvCoverageError, require_ohlcv_coverage
from .naver_history import fetch_naver_date_range_ohlcv, verify_adjusted_overlap
from .ohlcv_quality import normalize_ohlcv


@dataclass(frozen=True)
class OhlcvComparison:
    """Summary of a two-provider OHLCV comparison."""

    ticker: str
    common_rows: int
    close_values_match: bool
    pykrx_rows: int
    fdr_rows: int


def _normalize_security_codes(frame: DataFrame) -> tuple[DataFrame, list[str]]:
    """Normalize valid KRX codes and report provider rows that were excluded."""

    normalized_codes: list[str | None] = []
    invalid_codes: list[str] = []
    for value in frame["Code"]:
        try:
            normalized_codes.append(normalize_ticker(value))
        except ValueError:
            normalized_codes.append(None)
            invalid_codes.append(str(value))

    normalized = pd.Series(normalized_codes, index=frame.index, dtype="string")
    valid = normalized.notna()
    result = frame.loc[valid].copy()
    result["Code"] = normalized.loc[valid]
    return result, invalid_codes


def normalize_security_master(snapshot: DataFrame, description: DataFrame) -> DataFrame:
    """Merge FDR KRX snapshot and KRX-DESC into the canonical security master."""

    if snapshot.empty:
        raise MarketDataError("FinanceDataReader KRX snapshot returned no rows.")
    if description.empty:
        raise MarketDataError("FinanceDataReader KRX-DESC returned no rows.")

    required_snapshot = {"Code", "Name", "Market"}
    required_description = {"Code", "Name", "Market", "Industry"}
    if missing := required_snapshot.difference(snapshot.columns):
        raise MarketDataError(f"KRX snapshot missing columns: {sorted(missing)}")
    if missing := required_description.difference(description.columns):
        raise MarketDataError(f"KRX-DESC missing columns: {sorted(missing)}")

    snap, invalid_snapshot_codes = _normalize_security_codes(snapshot)
    desc, invalid_description_codes = _normalize_security_codes(description)
    if snap.empty:
        raise MarketDataError("KRX snapshot contains no valid numeric ticker codes.")
    if desc.empty:
        raise MarketDataError("KRX-DESC contains no valid numeric ticker codes.")

    snap = snap.rename(
        columns={
            "Code": "ticker",
            "Name": "snapshot_name",
            "Market": "snapshot_market",
            "Dept": "snapshot_listing_board",
            "ChagesRatio": "change_ratio",
            "ChangesRatio": "change_ratio",
            "Close": "close",
            "ChangeCode": "change_code",
            "Changes": "changes",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Volume": "volume",
            "Amount": "amount",
            "Marcap": "market_cap",
            "Stocks": "shares",
            "MarketId": "market_id",
        }
    )
    desc = desc.rename(
        columns={
            "Code": "ticker",
            "Name": "name",
            "Market": "market",
            # FDR's Sector is a listing board such as 벤처기업부/우량기업부,
            # not an economic sector. Keep the semantic distinction explicit.
            "Sector": "listing_board",
            "Industry": "industry",
            "Products": "products",
            "ListingDate": "listing_date",
            "SettleMonth": "settle_month",
            "Representative": "representative",
            "HomePage": "homepage",
            "Region": "region",
        }
    )

    snapshot_columns = [
        column
        for column in (
            "ticker",
            "snapshot_name",
            "snapshot_market",
            "snapshot_listing_board",
            "close",
            "change_code",
            "changes",
            "change_ratio",
            "open",
            "high",
            "low",
            "volume",
            "amount",
            "market_cap",
            "shares",
            "market_id",
        )
        if column in snap.columns
    ]
    master = desc.merge(snap[snapshot_columns], on="ticker", how="outer", validate="1:1")

    if "name" not in master:
        master["name"] = pd.NA
    if "market" not in master:
        master["market"] = pd.NA
    if "listing_board" not in master:
        master["listing_board"] = pd.NA

    for fallback_column in (
        "snapshot_name",
        "snapshot_market",
        "snapshot_listing_board",
    ):
        if fallback_column not in master:
            master[fallback_column] = pd.Series(pd.NA, index=master.index, dtype="object")

    master["name"] = master["name"].fillna(master["snapshot_name"])
    master["market"] = master["market"].fillna(master["snapshot_market"])
    master["listing_board"] = master["listing_board"].fillna(
        master["snapshot_listing_board"]
    )
    master["industry"] = master["industry"].astype("string").str.strip().replace("", pd.NA)
    master["industry_status"] = master["industry"].notna().map(
        {True: "classified", False: "candidate"}
    )
    master["source"] = "FinanceDataReader:KRX_CACHE+KRX_DESC_CACHE"
    master["retrieved_at"] = _retrieved_at()

    master = master.drop(
        columns=["snapshot_name", "snapshot_market", "snapshot_listing_board"],
        errors="ignore",
    )
    master = master.sort_values(["market", "ticker"], na_position="last").reset_index(drop=True)
    if master["ticker"].duplicated().any():
        duplicates = master.loc[master["ticker"].duplicated(), "ticker"].tolist()
        raise MarketDataError(f"Duplicate tickers in security master: {duplicates[:10]}")
    master.attrs["filtered_invalid_ticker_codes"] = {
        "KRX": invalid_snapshot_codes,
        "KRX-DESC": invalid_description_codes,
    }
    return master


def fetch_security_master(
    listing_fetcher: Callable[[str], DataFrame] | None = None,
) -> DataFrame:
    """Load the public FDR KRX master, tolerating a failed quote snapshot.

    FinanceDataReader's ``KRX`` and ``KRX-DESC`` routes are independent public
    downloads. The descriptive route contains the complete listed-security
    universe, so it remains a safe master source when only the current-quote
    snapshot endpoint is temporarily unavailable. A description failure is
    not replaced with the quote snapshot because doing so would erase stored
    listing dates and industries during an upsert.
    """

    if listing_fetcher is None:
        try:
            import FinanceDataReader as fdr
        except Exception as error:  # noqa: BLE001
            raise MarketDataError(
                f"FinanceDataReader import failed: {type(error).__name__}: {error}"
            ) from error
        listing_fetcher = fdr.StockListing

    frames: dict[str, DataFrame] = {}
    errors: dict[str, str] = {}
    for route in ("KRX", "KRX-DESC"):
        try:
            frame = listing_fetcher(route)
            if frame.empty:
                raise MarketDataError(f"FinanceDataReader {route} returned no rows.")
            frames[route] = frame
        except Exception as error:  # noqa: BLE001
            errors[route] = f"{type(error).__name__}: {error}"

    description = frames.get("KRX-DESC")
    if description is None:
        detail = "; ".join(f"{route}={message}" for route, message in errors.items())
        raise MarketDataError(
            "FinanceDataReader security-master description is unavailable"
            + (f": {detail}" if detail else "")
        )

    snapshot = frames.get("KRX")
    if snapshot is None:
        required = {"Code", "Name", "Market"}
        if missing := required.difference(description.columns):
            raise MarketDataError(
                f"KRX-DESC cannot supply the fallback universe; missing {sorted(missing)}"
            )
        snapshot = description[["Code", "Name", "Market"]].copy()

    master = normalize_security_master(snapshot, description)
    mode = "full" if "KRX" in frames else "description_only"
    master["source"] = (
        "FinanceDataReader:KRX_CACHE+KRX_DESC_CACHE"
        if mode == "full"
        else "FinanceDataReader:KRX_DESC_CACHE"
    )
    master.attrs["listing_mode"] = mode
    master.attrs["provider_errors"] = errors
    return master


def _normalize_ohlcv(
    frame: DataFrame,
    source: str,
    ticker: str,
    *,
    recovery_mode: bool = False,
) -> DataFrame:
    """Compatibility entry point; quality policy lives in its own module."""
    return normalize_ohlcv(
        frame, source, ticker,
        source_url=f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day",
        recovery_mode=recovery_mode,
    )


def fetch_pykrx_naver_ohlcv(
    ticker: str,
    start: str | dt.date | dt.datetime,
    end: str | dt.date | dt.datetime,
    *,
    recovery_mode: bool = False,
) -> DataFrame:
    """Fetch adjusted OHLCV through pykrx's login-free Naver route."""

    code = normalize_ticker(ticker)
    start_date = normalize_date(start)
    end_date = normalize_date(end)
    if start_date > end_date:
        raise ValueError("start must not be later than end")

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"pkg_resources is deprecated as an API.*",
            category=UserWarning,
        )
        from pykrx import stock

    frame = stock.get_market_ohlcv(
        start_date.strftime("%Y%m%d"),
        end_date.strftime("%Y%m%d"),
        code,
        adjusted=True,
    )
    return _normalize_ohlcv(
        frame,
        "pykrx:NAVER_ADJUSTED",
        code,
        recovery_mode=recovery_mode,
    )


def fetch_fdr_naver_ohlcv(
    ticker: str,
    start: str | dt.date | dt.datetime,
    end: str | dt.date | dt.datetime,
    *,
    recovery_mode: bool = False,
) -> DataFrame:
    """Fetch adjusted OHLCV from FinanceDataReader's explicit Naver route."""

    import FinanceDataReader as fdr

    code = normalize_ticker(ticker)
    start_date = normalize_date(start)
    end_date = normalize_date(end)
    if start_date > end_date:
        raise ValueError("start must not be later than end")
    frame = fdr.DataReader(
        f"NAVER:{code}",
        start_date.isoformat(),
        end_date.isoformat(),
    )
    return _normalize_ohlcv(
        frame,
        "FinanceDataReader:NAVER_ADJUSTED",
        code,
        recovery_mode=recovery_mode,
    )


def _fetch_pykrx_recovery_ohlcv(
    ticker: str, start: object, end: object
) -> DataFrame:
    return fetch_pykrx_naver_ohlcv(  # type: ignore[arg-type]
        ticker, start, end, recovery_mode=True
    )


def _fetch_fdr_recovery_ohlcv(
    ticker: str, start: object, end: object
) -> DataFrame:
    return fetch_fdr_naver_ohlcv(  # type: ignore[arg-type]
        ticker, start, end, recovery_mode=True
    )


def _fetch_naver_recovery_history(
    ticker: str, start: object, end: object
) -> DataFrame:
    return fetch_naver_date_range_ohlcv(
        ticker, start, end, recovery_mode=True
    )


def fetch_ohlcv(
    ticker: str,
    start: str | dt.date | dt.datetime,
    end: str | dt.date | dt.datetime,
    *,
    primary: Callable[[str, object, object], DataFrame] = fetch_pykrx_naver_ohlcv,
    fallback: Callable[[str, object, object], DataFrame] = fetch_fdr_naver_ohlcv,
    history_provider: Callable[[str, object, object], DataFrame] | None = (
        fetch_naver_date_range_ohlcv
    ),
) -> DataFrame:
    """Require coverage, then use a date-range route with a checked price basis.

Callers with a security master pass the later of listing date and requested
start. A recent-only response is retained as a comparison reference, never
returned as a successful multi-decade download.
"""
    code = normalize_ticker(ticker)
    start_date, end_date = normalize_date(start), normalize_date(end)
    if start_date > end_date:
        raise ValueError("start must not be later than end")
    errors: list[str] = []
    references: list[DataFrame] = []
    coverage_error: OhlcvCoverageError | None = None
    for position, (name, provider) in enumerate((("primary", primary), ("fallback", fallback))):
        try:
            frame = provider(code, start_date, end_date)
            if not frame.empty:
                references.append(frame)
            require_ohlcv_coverage(frame, start_date, end_date)
            frame.attrs["fallback_used"] = position > 0
            frame.attrs["provider_attempts"] = errors
            if errors:
                frame.attrs["primary_error"] = errors[0]
            return frame
        except Exception as error:  # noqa: BLE001
            errors.append(f"{name}={type(error).__name__}: {error}")
            if isinstance(error, OhlcvCoverageError):
                coverage_error = error

    if history_provider is not None and references:
        try:
            candidate = history_provider(code, start_date, end_date)
            source_history_start = candidate.attrs.get("source_history_start")
            require_ohlcv_coverage(
                candidate,
                source_history_start or start_date,
                end_date,
            )
            reference = max(references, key=len)
            verify_adjusted_overlap(reference, candidate)
            candidate.attrs["fallback_used"] = True
            candidate.attrs["primary_error"] = errors[0]
            candidate.attrs["provider_attempts"] = errors
            return candidate
        except Exception as error:  # noqa: BLE001
            errors.append(f"date_range={type(error).__name__}: {error}")
            if isinstance(error, OhlcvCoverageError):
                coverage_error = error
    elif history_provider is not None:
        errors.append("date_range=No adjusted reference available to verify the price basis")
    message = "All OHLCV routes failed. " + "; ".join(errors)
    if coverage_error is not None:
        raise OhlcvCoverageError(coverage_error.coverage, message) from coverage_error
    raise MarketDataError(message)


def fetch_ohlcv_for_recovery(
    ticker: str,
    start: str | dt.date | dt.datetime,
    end: str | dt.date | dt.datetime,
    *,
    primary: Callable[[str, object, object], DataFrame] = (
        _fetch_pykrx_recovery_ohlcv
    ),
    fallback: Callable[[str, object, object], DataFrame] = (
        _fetch_fdr_recovery_ohlcv
    ),
    history_provider: Callable[[str, object, object], DataFrame] | None = (
        _fetch_naver_recovery_history
    ),
) -> DataFrame:
    """Route only reviewed failures through the bounded recovery policy.

    The recent providers remain comparison references when they are capped.
    A date-range candidate is accepted only after adjusted closes overlap and
    after its explicit source/quality limitations pass the recovery checks.
    """

    code = normalize_ticker(ticker)
    start_date, end_date = normalize_date(start), normalize_date(end)
    if start_date > end_date:
        raise ValueError("start must not be later than end")
    errors: list[str] = []
    references: list[DataFrame] = []
    coverage_error: OhlcvCoverageError | None = None
    providers = (("primary", primary), ("fallback", fallback))
    for position, (name, provider) in enumerate(providers):
        try:
            frame = provider(code, start_date, end_date)
            if not frame.empty:
                references.append(frame)
            require_ohlcv_coverage(
                frame,
                start_date,
                end_date,
                allow_quality_limit=True,
            )
            frame.attrs["fallback_used"] = position > 0
            frame.attrs["provider_attempts"] = errors
            if errors:
                frame.attrs["primary_error"] = errors[0]
            return frame
        except Exception as error:  # noqa: BLE001
            errors.append(f"{name}={type(error).__name__}: {error}")
            if isinstance(error, OhlcvCoverageError):
                coverage_error = error

    if history_provider is not None and references:
        try:
            candidate = history_provider(code, start_date, end_date)
            require_ohlcv_coverage(
                candidate,
                start_date,
                end_date,
                source_history_start=candidate.attrs.get("source_history_start"),
                allow_source_limit=True,
                allow_quality_limit=True,
            )
            reference = max(references, key=len)
            verify_adjusted_overlap(reference, candidate)
            candidate.attrs["fallback_used"] = True
            candidate.attrs["primary_error"] = errors[0]
            candidate.attrs["provider_attempts"] = errors
            candidate.attrs["recovery_mode"] = True
            return candidate
        except Exception as error:  # noqa: BLE001
            errors.append(f"date_range={type(error).__name__}: {error}")
            if isinstance(error, OhlcvCoverageError):
                coverage_error = error
    elif history_provider is not None:
        errors.append(
            "date_range=No adjusted reference available to verify the price basis"
        )
    message = "All recovery OHLCV routes failed. " + "; ".join(errors)
    if coverage_error is not None:
        raise OhlcvCoverageError(coverage_error.coverage, message) from coverage_error
    raise MarketDataError(message)


def compare_ohlcv_sources(
    ticker: str,
    start: str | dt.date | dt.datetime,
    end: str | dt.date | dt.datetime,
) -> OhlcvComparison:
    """Compare adjusted closes from pykrx and FinanceDataReader."""

    code = normalize_ticker(ticker)
    pykrx_frame = fetch_pykrx_naver_ohlcv(code, start, end)
    fdr_frame = fetch_fdr_naver_ohlcv(code, start, end)
    common = pykrx_frame.index.intersection(fdr_frame.index)
    match = bool(
        len(common)
        and pykrx_frame.loc[common, "close"].astype("int64").tolist()
        == fdr_frame.loc[common, "close"].astype("int64").tolist()
    )
    return OhlcvComparison(
        ticker=code,
        common_rows=len(common),
        close_values_match=match,
        pykrx_rows=len(pykrx_frame),
        fdr_rows=len(fdr_frame),
    )
