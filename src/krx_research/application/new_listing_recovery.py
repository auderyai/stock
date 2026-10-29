from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Protocol

import pandas as pd
from pandas import DataFrame

from krx_research.analytics.screeners import exclude_spac_securities
from krx_research.collectors import normalize_ticker, require_ohlcv_coverage
from krx_research.collectors.market_data import normalize_date


class NewListingRecoveryRepository(Protocol):
    def get_ohlcv(self, ticker: str, start: dt.date, end: dt.date) -> DataFrame: ...
    def upsert_ohlcv(self, frame: DataFrame) -> int: ...


class NewListingRecoveryService:
    """Recover provider-confirmed OHLCV gaps for recently listed KRX stocks."""

    def __init__(
        self,
        repository: NewListingRecoveryRepository,
        fetcher: Callable[[str, object, object], DataFrame],
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher

    def recover(
        self,
        master: DataFrame,
        since: object,
        as_of: object,
        *,
        tickers: tuple[str, ...] = (),
        max_tickers: int = 0,
        apply: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        start, end = normalize_date(since), normalize_date(as_of)
        if max_tickers < 0:
            raise ValueError("max_tickers는 0 이상이어야 합니다.")
        candidates = self._candidates(master, start, end, tickers)
        if max_tickers > 0:
            candidates = candidates[:max_tickers]
        results, failures = [], []
        for position, row in enumerate(candidates, 1):
            code, listing = row["ticker"], row["listing_date"]
            if progress:
                progress(f"[{position}/{len(candidates)}] {code} {row['name']}")
            try:
                fetched = self._fetcher(code, listing, end)
                coverage = require_ohlcv_coverage(
                    fetched,
                    listing,
                    end,
                    listing_date=listing,
                    source_history_start=fetched.attrs.get("source_history_start"),
                )
                stored = self._repository.get_ohlcv(code, listing, end)
                missing_dates = self._dates(fetched).difference(self._dates(stored))
                written = 0
                if apply and len(missing_dates):
                    missing = fetched.loc[self._dates(fetched).isin(missing_dates)].copy()
                    missing["stock_code"] = code
                    written = self._repository.upsert_ohlcv(missing)
                    remaining = missing_dates.difference(
                        self._dates(self._repository.get_ohlcv(code, listing, end))
                    )
                    if len(remaining):
                        raise RuntimeError(f"DB 저장 후 {len(remaining)}개 거래일이 누락됐습니다.")
                results.append({
                    **row,
                    "missing_rows": len(missing_dates),
                    "rows_written": written,
                    "coverage": coverage,
                })
            except Exception as error:  # noqa: BLE001
                failures.append({"ticker": code, "error": f"{type(error).__name__}: {error}"})
        return {
            "status": "completed" if not failures else "failed",
            "apply": apply,
            "as_of": end.isoformat(),
            "candidates": len(candidates),
            "missing_rows": sum(int(row["missing_rows"]) for row in results),
            "rows_written": sum(int(row["rows_written"]) for row in results),
            "results": results,
            "failures": failures,
        }

    @staticmethod
    def _candidates(
        master: DataFrame,
        since: dt.date,
        as_of: dt.date,
        tickers: tuple[str, ...],
    ) -> list[dict[str, object]]:
        frame = master.copy()
        if "name" not in frame and "stock_name" in frame:
            frame = frame.rename(columns={"stock_name": "name"})
        frame = exclude_spac_securities(frame)
        selected = {normalize_ticker(code) for code in tickers}
        records: list[dict[str, object]] = []
        for row in frame.to_dict("records"):
            try:
                code = normalize_ticker(row.get("ticker") or row.get("stock_code"))
                raw_listing = row["listing_date"]
                if pd.isna(raw_listing):
                    continue
                listing = normalize_date(
                    raw_listing
                    if isinstance(raw_listing, (dt.date, dt.datetime))
                    else str(raw_listing).removesuffix(".0")
                )
            except (KeyError, TypeError, ValueError):
                continue
            market = str(row.get("market") or "").upper()
            in_scope = code in selected if selected else listing >= since
            if listing <= as_of and in_scope and market in {"KOSPI", "KOSDAQ"}:
                records.append({
                    "ticker": code,
                    "name": str(row.get("name") or code),
                    "market": market,
                    "listing_date": listing,
                })
        return sorted(records, key=lambda row: (row["listing_date"], row["ticker"]))

    @staticmethod
    def _dates(frame: DataFrame) -> pd.DatetimeIndex:
        values = frame["trade_date"] if "trade_date" in frame else frame.index
        dates = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"))
        return dates.dropna().normalize().unique()
