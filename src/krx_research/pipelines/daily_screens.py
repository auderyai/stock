"""Persist deterministic same-date market screens to PostgreSQL and CSV."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from pandas import DataFrame

from krx_research.analytics import (
    EMA_DEFAULT_GAP_TOLERANCE,
    EMA_DEFAULT_MIN_SIMILARITY,
    SCREEN_FORMULA_VERSION,
    build_market_screens,
)
from krx_research.collectors.market_data import normalize_date
from krx_research.database import ResearchStore

SCREEN_FILENAMES = {
    "ema_similarity": "01_ema_similarity.csv",
    "high_52w": "02_52week_high.csv",
    "bollinger_breakout": "03_weekly_bollinger_breakout.csv",
    "weekly_return": "04_weekly_return_top50.csv",
}


def _replace_with_retry(
    source: Path,
    target: Path,
    *,
    attempts: int = 20,
    initial_delay: float = 0.05,
) -> None:
    """Replace one CSV after transient Windows scanner/share locks clear."""

    delay = initial_delay
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if attempt + 1 >= attempts:
                raise PermissionError(
                    error.errno,
                    f"Could not replace {target}; close the CSV in Excel and retry",
                    str(target),
                ) from error
            time.sleep(delay)
            delay = min(delay * 1.5, 0.5)


def _export_csv_files(frames: Mapping[str, DataFrame], output_directory: Path) -> dict[str, str]:
    output_directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for screen_type, filename in SCREEN_FILENAMES.items():
        frame = frames[screen_type]
        target = output_directory / filename
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            frame.to_csv(temporary, index=False, encoding="utf-8-sig")
            _replace_with_retry(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        paths[screen_type] = str(target.resolve())
    return paths


def run_daily_screens(
    store: ResearchStore,
    *,
    output_directory: str | Path,
    as_of_date: object | None = None,
    comparison_ticker: object | None = "222800",
    top_n: int = 50,
    ema_min_similarity: float = EMA_DEFAULT_MIN_SIMILARITY,
    ema_gap_tolerance: float = EMA_DEFAULT_GAP_TOLERANCE,
) -> dict[str, object]:
    """Build, export, and persist all four screens from local data only."""

    requested_date = None if as_of_date is None else normalize_date(as_of_date)  # type: ignore[arg-type]
    resolved_date = store.latest_technical_indicator_date(requested_date)
    if resolved_date is None:
        suffix = "" if requested_date is None else f" on or before {requested_date}"
        raise ValueError(f"No technical indicators are available{suffix}")

    snapshot = store.get_screen_snapshot(resolved_date)
    result = build_market_screens(
        snapshot,
        as_of_date=resolved_date,
        comparison_ticker=comparison_ticker,
        top_n=top_n,
        ema_min_similarity=ema_min_similarity,
        ema_gap_tolerance=ema_gap_tolerance,
    )
    destination = Path(output_directory).expanduser().resolve()
    frames = result.frames()
    csv_paths = _export_csv_files(frames, destination)
    run_id = store.save_screen_run(
        as_of_date=result.as_of_date,
        comparison_ticker=result.comparison_ticker,
        formula_version=SCREEN_FORMULA_VERSION,
        universe_count=result.universe_count,
        frames=frames,
        output_directory=destination,
    )
    counts = {screen_type: len(frame) for screen_type, frame in frames.items()}
    latest_price_date = store.latest_adjusted_ohlcv_date(requested_date)
    if requested_date is None:
        date_resolution = "latest_available"
    elif resolved_date == requested_date:
        date_resolution = "requested_date_available"
    else:
        date_resolution = "latest_available_before_requested_date"
    return {
        "status": "completed",
        "run_id": run_id,
        "schema_version": store.schema_version,
        "requested_as_of_date": (None if requested_date is None else requested_date.isoformat()),
        "as_of_date": resolved_date.isoformat(),
        "latest_adjusted_ohlcv_date": (
            None if latest_price_date is None else latest_price_date.isoformat()
        ),
        "date_resolution": date_resolution,
        "comparison_ticker": result.comparison_ticker,
        "ema_min_similarity": float(ema_min_similarity),
        "ema_gap_tolerance": float(ema_gap_tolerance),
        "universe_count": result.universe_count,
        "result_counts": counts,
        "csv_paths": csv_paths,
        "screen_run_rows_total": store.count_rows("screen_runs"),
        "screen_result_rows_total": store.count_rows("screen_results"),
        "quick_check": store.quick_check(),
        "price_basis": "adjusted",
        "trading_value_basis": "estimated_close_x_volume",
        "network_used": False,
        "krx_login_used": False,
    }
