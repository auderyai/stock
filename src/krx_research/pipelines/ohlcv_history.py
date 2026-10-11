"""Bounded, resumable, login-free adjusted OHLCV history collection."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor, as_completed
from contextlib import nullcontext

from pandas import DataFrame

from krx_research.collectors import (
    OhlcvCoverageError,
    effective_history_start,
    fetch_ohlcv,
    normalize_ticker,
    require_ohlcv_coverage,
)
from krx_research.collectors.market_data import normalize_date
from krx_research.database import ResearchStore

OHLCV_HISTORY_SOURCE = (
    "pykrx:NAVER_ADJUSTED|FinanceDataReader:NAVER_ADJUSTED|NAVER:DATE_RANGE_ADJUSTED"
)


def _emit_progress(
    progress: Callable[[dict[str, object]], None] | None,
    event: dict[str, object],
) -> None:
    """Best-effort progress must never invalidate a completed DB checkpoint."""

    if progress is None:
        return
    try:
        progress(event)
    except Exception:  # noqa: BLE001
        return


def _fetch_with_retries(
    ticker: str,
    start: object,
    end: object,
    *,
    fetcher: Callable[[str, object, object], DataFrame],
    retry_attempts: int,
    retry_delay: float,
    sleeper: Callable[[float], None],
    listing_date: object | None = None,
) -> DataFrame:
    error: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            return fetcher(ticker, effective_history_start(start, listing_date), end)
        except OhlcvCoverageError:
            # Repeating the same capped response cannot extend its history.
            raise
        except Exception as caught:  # noqa: BLE001
            error = caught
            if attempt < retry_attempts:
                sleeper(retry_delay * attempt)
    if error is None:
        raise RuntimeError("OHLCV fetch failed without an exception")
    raise error


def sync_ohlcv_history(
    store: ResearchStore,
    tickers: list[object],
    start: object,
    end: object,
    *,
    fetcher: Callable[[str, object, object], DataFrame] = fetch_ohlcv,
    force: bool = False,
    max_tickers: int = 10,
    workers: int = 1,
    retry_attempts: int = 3,
    retry_delay: float = 2.0,
    request_delay: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
    allow_quality_limit: bool = False,
    progress: Callable[[dict[str, object]], None] | None = None,
    include_diagnostics: bool = True,
    thread_executor: Executor | None = None,
) -> dict[str, object]:
    """Fetch a bounded ticker batch and persist checkpoints for safe resume."""

    if max_tickers < 1:
        raise ValueError("max_tickers must be at least 1")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    if retry_attempts < 1:
        raise ValueError("retry_attempts must be at least 1")
    if retry_delay < 0 or request_delay < 0:
        raise ValueError("delays must not be negative")

    start_date = normalize_date(start)  # type: ignore[arg-type]
    end_date = normalize_date(end)  # type: ignore[arg-type]
    if start_date > end_date:
        raise ValueError("start must not be later than end")
    universe = sorted({normalize_ticker(ticker) for ticker in tickers})
    if not universe:
        raise ValueError("At least one ticker is required")

    covered = set() if force else store.covered_ohlcv_history_tickers(
        universe,
        start_date,
        end_date,
    )
    pending = [ticker for ticker in universe if ticker not in covered]
    selected = pending[:max_tickers]
    run_id = store.start_ohlcv_history_run(
        start_date,
        end_date,
        source=OHLCV_HISTORY_SOURCE,
        tickers_requested=len(universe),
        tickers_selected=len(selected),
    )

    futures: dict[Future[DataFrame], str] = {}
    completed_tickers: list[str] = []
    fallback_tickers: list[str] = []
    source_limited_tickers: list[str] = []
    quality_limited_tickers: list[str] = []
    failures: list[dict[str, str]] = []
    rows_written = 0
    coverage_results: dict[str, dict[str, object]] = {}
    quality_results: dict[str, dict[str, object]] = {}
    adjusted_overlap_rows: dict[str, int] = {}
    listing_dates = {
        ticker: (store.get_security(ticker) or {}).get("listing_date")
        for ticker in selected
    }
    executor_context = (
        ThreadPoolExecutor(max_workers=workers)
        if thread_executor is None
        else nullcontext(thread_executor)
    )
    with executor_context as executor:
        for position, ticker in enumerate(selected):
            store.start_ohlcv_history_attempt(run_id, ticker)
            future = executor.submit(
                _fetch_with_retries,
                ticker,
                start_date,
                end_date,
                fetcher=fetcher,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
                sleeper=sleeper,
                listing_date=listing_dates[ticker],
            )
            futures[future] = ticker
            if position < len(selected) - 1 and request_delay:
                sleeper(request_delay)

        for future in as_completed(futures):
            ticker = futures[future]
            try:
                frame = future.result()
                if frame.empty and not frame.attrs.get("quality_events"):
                    raise ValueError(f"Provider returned no rows for {ticker}")
                coverage = require_ohlcv_coverage(
                    frame,
                    start_date,
                    end_date,
                    listing_date=listing_dates[ticker],
                    source_history_start=frame.attrs.get("source_history_start"),
                    allow_source_limit=True,
                    allow_quality_limit=allow_quality_limit,
                )
                sources = frame["source"].dropna().astype(str).unique().tolist()
                if not sources and frame.attrs.get("source"):
                    sources = [str(frame.attrs["source"])]
                if len(sources) != 1:
                    raise ValueError(f"Expected one source for {ticker}, received {sources}")
                written = store.upsert_ohlcv(frame)
                fallback_used = bool(frame.attrs.get("fallback_used", False))
                store.complete_ohlcv_history_attempt(
                    run_id,
                    ticker,
                    rows_written=written,
                    source=sources[0],
                    fallback_used=fallback_used,
                    coverage=coverage,
                )
                rows_written += written
                completed_tickers.append(ticker)
                coverage_results[ticker] = coverage
                quality_results[ticker] = dict(
                    frame.attrs.get("quality_summary", {})
                )
                if frame.attrs.get("adjusted_overlap_rows") is not None:
                    adjusted_overlap_rows[ticker] = int(
                        frame.attrs["adjusted_overlap_rows"]
                    )
                if fallback_used:
                    fallback_tickers.append(ticker)
                if coverage["status"] == "source_limited":
                    source_limited_tickers.append(ticker)
                if coverage["status"] == "quality_limited":
                    quality_limited_tickers.append(ticker)
                _emit_progress(
                    progress,
                    {
                        "completed": len(completed_tickers) + len(failures),
                        "total": len(selected),
                        "ticker": ticker,
                        "status": "completed",
                        "rows_written": written,
                    },
                )
            except Exception as error:  # noqa: BLE001
                store.fail_ohlcv_history_attempt(run_id, ticker, error)
                failure = {
                    "ticker": ticker,
                    "error": f"{type(error).__name__}: {error}",
                }
                failures.append(failure)
                _emit_progress(
                    progress,
                    {
                        "completed": len(completed_tickers) + len(failures),
                        "total": len(selected),
                        "ticker": ticker,
                        "status": "failed",
                        "rows_written": 0,
                    },
                )

    remaining_tickers = len(pending) - len(selected)
    if failures and not completed_tickers and not remaining_tickers:
        status = "failed"
    elif failures or remaining_tickers:
        status = "partial"
    else:
        status = "completed"
    error_summary = "; ".join(
        f"{failure['ticker']}={failure['error']}" for failure in failures
    )
    store.finish_ohlcv_history_run(
        run_id,
        status=status,
        error_summary=error_summary or None,
    )
    run = store.get_ohlcv_history_run(run_id)
    if run is None:
        raise RuntimeError(f"Completed OHLCV history run disappeared: {run_id}")

    return {
        "run_id": run_id,
        "status": status,
        "requested_start": start_date.isoformat(),
        "requested_end": end_date.isoformat(),
        "tickers_requested": len(universe),
        "previously_covered_tickers": len(covered.intersection(universe)),
        "selected_tickers": selected,
        "completed_tickers": sorted(completed_tickers),
        "coverage": coverage_results,
        "quality": quality_results,
        "adjusted_overlap_rows": adjusted_overlap_rows,
        "fallback_tickers": sorted(fallback_tickers),
        "source_limited_tickers": sorted(source_limited_tickers),
        "quality_limited_tickers": sorted(quality_limited_tickers),
        "failures": sorted(failures, key=lambda item: item["ticker"]),
        "rows_written": rows_written,
        "remaining_tickers": remaining_tickers,
        "ohlcv_daily_rows_total": (
            store.count_rows("ohlcv_daily") if include_diagnostics else None
        ),
        "run": run,
        "quick_check": store.quick_check() if include_diagnostics else "deferred",
        "price_basis": "adjusted",
        "workers": workers,
        "krx_login_used": False,
    }
