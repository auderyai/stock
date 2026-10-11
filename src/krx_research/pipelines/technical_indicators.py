"""Bounded and resumable calculation of locally derived technical indicators."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Executor, ProcessPoolExecutor
from multiprocessing import get_context

import pandas as pd

from krx_research.analytics import (
    FORMULA_VERSION,
    TRADING_DAYS_52W,
    calculate_incremental_technical_indicators,
    calculate_technical_indicators,
)
from krx_research.collectors import normalize_ticker
from krx_research.database import ResearchStore


def _calculate_one_indicator(payload):
    ticker, frame, append_after, previous_daily, total_observations = payload
    try:
        if append_after is None or previous_daily is None:
            result = calculate_technical_indicators(frame, ticker=ticker)
        else:
            result = calculate_incremental_technical_indicators(
                frame,
                ticker=ticker,
                append_after=append_after,
                previous_daily=previous_daily,
                total_observations=total_observations,
            )
        return ticker, result, None
    except Exception as error:  # noqa: BLE001
        return ticker, None, f"{type(error).__name__}: {error}"


def sync_technical_indicators(
    store: ResearchStore,
    tickers: list[object],
    *,
    force: bool = False,
    max_tickers: int = 50,
    workers: int = 1,
    process_executor: Executor | None = None,
    statuses: Mapping[str, Mapping[str, object]] | None = None,
    include_diagnostics: bool = True,
) -> dict[str, object]:
    """Calculate a bounded stale ticker batch entirely from local adjusted data."""

    if max_tickers < 1:
        raise ValueError("max_tickers must be at least 1")
    if not 1 <= workers <= 12:
        raise ValueError("workers must be between 1 and 12")
    if process_executor is not None and workers == 1:
        raise ValueError("process_executor requires at least 2 workers")
    universe = sorted({normalize_ticker(ticker) for ticker in tickers})
    if not universe:
        raise ValueError("At least one ticker is required")

    status_by_ticker = (
        {normalize_ticker(code): dict(status) for code, status in statuses.items()}
        if statuses is not None
        else store.get_technical_indicator_statuses(
            universe,
            formula_version=FORMULA_VERSION,
        )
    )
    signatures: dict[str, Mapping[str, object]] = {}
    failures: list[dict[str, str]] = []
    for ticker in universe:
        status = status_by_ticker.get(ticker, {})
        signature = status.get("signature")
        if not isinstance(signature, Mapping):
            failures.append(
                {
                    "ticker": ticker,
                    "error": "No adjusted OHLCV rows in the local database",
                }
            )
        else:
            signatures[ticker] = signature

    fresh = set()
    if not force:
        fresh = {
            ticker for ticker in signatures if status_by_ticker[ticker].get("fresh") is True
        }
    pending = [ticker for ticker in universe if ticker in signatures and ticker not in fresh]
    selected = pending[:max_tickers]

    completed_tickers: list[str] = []
    insufficient_history_tickers: list[str] = []
    appended_tickers: list[str] = []
    full_replace_tickers: list[str] = []
    daily_rows_replaced = 0
    weekly_rows_replaced = 0
    frames = {}
    append_after: dict[str, str | None] = {}
    previous_daily: dict[str, Mapping[str, object] | None] = {}
    incremental_calculation_tickers: list[str] = []
    for ticker in selected:
        try:
            append_after[ticker] = (
                None
                if force
                else store.technical_indicator_append_after(
                    ticker,
                    formula_version=FORMULA_VERSION,
                    signature=signatures[ticker],
                )
            )
            previous_daily[ticker] = None
            cutoff = append_after[ticker]
            if cutoff is not None:
                prior = store.get_technical_indicator_daily_row(ticker, cutoff)
                previous_count = 0 if prior is None else int(prior["observations"])
                appended_count = int(signatures[ticker]["input_row_count"]) - previous_count
                if (
                    prior is not None
                    and previous_count >= 448
                    and appended_count > 0
                ):
                    recent = store.get_adjusted_ohlcv_tail(
                        ticker,
                        TRADING_DAYS_52W + appended_count,
                    )
                    cutoff_timestamp = pd.Timestamp(cutoff)
                    prior_rows = recent.loc[recent.index <= cutoff_timestamp]
                    if (
                        cutoff_timestamp in recent.index
                        and len(prior_rows) >= TRADING_DAYS_52W
                    ):
                        frames[ticker] = recent
                        previous_daily[ticker] = prior
                        incremental_calculation_tickers.append(ticker)
            if ticker not in frames:
                frames[ticker] = store.get_adjusted_ohlcv(ticker)
        except Exception as error:  # noqa: BLE001
            failures.append(
                {
                    "ticker": ticker,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    calculation_tickers = list(frames)
    payloads = [
        (
            ticker,
            frames[ticker],
            append_after[ticker] if previous_daily[ticker] is not None else None,
            previous_daily[ticker],
            int(signatures[ticker]["input_row_count"]),
        )
        for ticker in calculation_tickers
    ]
    if workers == 1 or len(calculation_tickers) < 2:
        calculations = [_calculate_one_indicator(payload) for payload in payloads]
    elif process_executor is not None:
        calculations = list(
            process_executor.map(
                _calculate_one_indicator,
                payloads,
                chunksize=1,
            )
        )
    else:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(calculation_tickers)),
            mp_context=get_context("spawn"),
        ) as executor:
            calculations = list(
                executor.map(
                    _calculate_one_indicator,
                    payloads,
                    chunksize=1,
                )
            )

    for ticker, result, calculation_error in calculations:
        if calculation_error is not None or result is None:
            failures.append(
                {
                    "ticker": ticker,
                    "error": calculation_error or "Indicator calculation returned no result",
                }
            )
            continue
        try:
            append_date = append_after[ticker]
            if append_date is None:
                daily_rows, weekly_rows = store.replace_technical_indicators(
                    ticker,
                    result.daily,
                    result.weekly,
                    formula_version=FORMULA_VERSION,
                    input_signature=signatures[ticker],
                    history_ready_448=result.history_ready_448,
                )
                full_replace_tickers.append(ticker)
            else:
                cutoff = pd.Timestamp(append_date)
                daily_tail = result.daily.loc[result.daily.index > cutoff]
                weekly_tail = result.weekly.loc[
                    pd.to_datetime(result.weekly["last_trade_date"]) > cutoff
                ]
                daily_rows, weekly_rows = store.append_technical_indicators(
                    ticker,
                    daily_tail,
                    weekly_tail,
                    formula_version=FORMULA_VERSION,
                    input_signature=signatures[ticker],
                    history_ready_448=result.history_ready_448,
                    append_after=append_date,
                )
                appended_tickers.append(ticker)
            daily_rows_replaced += daily_rows
            weekly_rows_replaced += weekly_rows
            completed_tickers.append(ticker)
            if not result.history_ready_448:
                insufficient_history_tickers.append(ticker)
        except Exception as error:  # noqa: BLE001
            failures.append(
                {
                    "ticker": ticker,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    remaining_tickers = len(pending) - len(selected)
    if failures and not completed_tickers and not remaining_tickers:
        status = "failed"
    elif failures or remaining_tickers:
        status = "partial"
    else:
        status = "completed"

    return {
        "status": status,
        "formula_version": FORMULA_VERSION,
        "tickers_requested": len(universe),
        "previously_fresh_tickers": len(fresh),
        "selected_tickers": selected,
        "completed_tickers": sorted(completed_tickers),
        "insufficient_history_tickers": sorted(insufficient_history_tickers),
        "appended_tickers": sorted(appended_tickers),
        "full_replace_tickers": sorted(full_replace_tickers),
        "failures": sorted(failures, key=lambda item: item["ticker"]),
        "daily_rows_replaced": daily_rows_replaced,
        "weekly_rows_replaced": weekly_rows_replaced,
        "remaining_tickers": remaining_tickers,
        "incremental_calculation_tickers": sorted(incremental_calculation_tickers),
        "technical_daily_rows_total": (
            store.count_rows("technical_indicators_daily") if include_diagnostics else None
        ),
        "technical_weekly_rows_total": (
            store.count_rows("technical_indicators_weekly") if include_diagnostics else None
        ),
        "technical_state_rows_total": (
            store.count_rows("technical_indicator_state") if include_diagnostics else None
        ),
        "quick_check": store.quick_check() if include_diagnostics else "deferred",
        "price_basis": "adjusted",
        "workers": workers,
        "network_used": False,
        "krx_login_used": False,
    }
