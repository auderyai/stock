"""Resilient security-master refresh for all configured database pipelines."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pandas import DataFrame

from krx_research.collectors import MarketDataError, fetch_security_master


class SecurityMasterStore(Protocol):
    """Storage methods required by the refresh policy."""

    def upsert_security_master(self, frame: DataFrame) -> int: ...

    def list_security_tickers(self, market: str = "ALL") -> list[str]: ...


def refresh_security_master(
    store: SecurityMasterStore,
    *,
    skip: bool = False,
    fetcher: Callable[[], DataFrame] = fetch_security_master,
) -> dict[str, object]:
    """Refresh the public master or retain an already populated DB universe.

    Provider failures must not stop a daily price update when the database
    already contains a usable security master. They remain explicit in the
    returned status and warning instead of being silently ignored.
    """

    cached_rows = len(store.list_security_tickers("ALL"))
    if skip:
        return {
            "status": "skipped",
            "rows_written": 0,
            "cached_rows": cached_rows,
            "listing_mode": None,
            "provider_errors": {},
            "filtered_invalid_ticker_codes": {},
            "warning": None,
        }

    try:
        frame = fetcher()
    except MarketDataError as error:
        if not cached_rows:
            raise MarketDataError(
                "Security-master refresh failed and the database has no cached tickers: "
                f"{error}"
            ) from error
        return {
            "status": "cached_fallback",
            "rows_written": 0,
            "cached_rows": cached_rows,
            "listing_mode": None,
            "provider_errors": {},
            "filtered_invalid_ticker_codes": {},
            "warning": f"{type(error).__name__}: {error}",
        }

    listing_mode = str(frame.attrs.get("listing_mode", "full"))
    provider_errors = dict(frame.attrs.get("provider_errors", {}))
    filtered_codes = dict(frame.attrs.get("filtered_invalid_ticker_codes", {}))
    if listing_mode == "full" or not cached_rows:
        rows_written = store.upsert_security_master(frame)
    else:
        # A description-only row has no current OHLCV snapshot columns. Keep
        # populated records untouched, while still admitting newly listed
        # tickers that were not present in the cached universe.
        existing = set(store.list_security_tickers("ALL"))
        additions = frame.loc[~frame["ticker"].astype(str).isin(existing)]
        rows_written = store.upsert_security_master(additions)
    cached_rows = len(store.list_security_tickers("ALL"))
    warning = None
    if listing_mode != "full":
        warning = "KRX quote snapshot unavailable; KRX-DESC supplied the listed universe."
    return {
        "status": "refreshed" if listing_mode == "full" else "description_fallback",
        "rows_written": rows_written,
        "cached_rows": cached_rows,
        "listing_mode": listing_mode,
        "provider_errors": provider_errors,
        "filtered_invalid_ticker_codes": filtered_codes,
        "warning": warning,
    }
