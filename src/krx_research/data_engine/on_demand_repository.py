"""PostgreSQL base-data readers used by the workstation GUI.

No candle, indicator, investor total, or screen result produced here is written
back to PostgreSQL.  The database remains a fact store and this module performs
the requested representation in memory.
"""

from __future__ import annotations

import datetime as dt
import threading
from concurrent.futures import CancelledError
from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics.chart_frames import build_chart_frame
from krx_research.analytics.on_demand_screening import (
    _prepare_history,
    build_overlay_snapshot,
    calculate_screen,
)
from krx_research.collectors.naver_investor import fetch_naver_investor_trend
from krx_research.data_engine.config import settings_from_database_target
from krx_research.analytics.investor import (
    aggregate_investor_flow,
    normalize_investor_code,
)
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.database.settings import PostgreSQLSettings
from krx_research.models.on_demand import OnDemandChartResult, OnDemandScreenResult
from krx_research.policies.workstation_options import TIMEFRAME_LABELS


SCREEN_CACHE_SECONDS = 300
DATABASE_VENUES = frozenset({"KRX", "NXT", "COMBINED"})
CHART_CACHE_SECONDS = 300
CHART_CACHE_MAX_TICKERS = 16
NAVER_INVESTOR_CACHE_SECONDS = 6 * 60 * 60
SCREEN_LOOKBACK_DAYS = {
    "ema_similarity": 2400,
    "high_52w": 520,
    "near_high_52w": 520,
    "bollinger_breakout": 300,
    "weekly_return": 45,
    "kospi_weekly_gainers": 45,
    "kosdaq_weekly_gainers": 45,
    "kospi200_daily_gainers": 45,
    "kosdaq150_daily_gainers": 45,
    "kospi200_kosdaq150_daily_gainers": 45,
    "kospi_daily_gainers": 45,
    "kosdaq_daily_gainers": 45,
    "kospi_kosdaq_daily_gainers": 45,
    "kospi_kosdaq_daily_trading_value": 45,
    "kospi_weekly_trading_value": 14,
    "kosdaq_weekly_trading_value": 14,
    "kospi_kosdaq_weekly_trading_value": 14,
    "kospi200_weekly_gainers": 45,
    "kosdaq150_weekly_gainers": 45,
    "kospi200_kosdaq150_weekly_gainers": 45,
}


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError()


def _append_live_chart_bar(
    raw: DataFrame,
    ticker: str,
    live_bar: dict[str, object] | None,
) -> tuple[DataFrame, bool]:
    """Return DB history with the cached live candle inserted or replaced."""

    if not live_bar:
        return raw, False
    trade_date = pd.to_datetime(live_bar.get("trade_date"), errors="coerce")
    if pd.isna(trade_date):
        return raw, False
    values = {
        "open_price": live_bar.get("open"),
        "high_price": live_bar.get("high"),
        "low_price": live_bar.get("low"),
        "close_price": live_bar.get("close"),
        "volume": live_bar.get("volume", 0),
        "amount": live_bar.get("estimated_trading_value", 0),
        "change_rate": live_bar.get("daily_return_pct"),
    }
    numeric = {
        key: pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        for key, value in values.items()
    }
    if any(pd.isna(numeric[key]) for key in ("open_price", "high_price", "low_price", "close_price")):
        return raw, False

    result = raw.copy(deep=True)
    if "trade_date" in result.columns:
        dates = pd.to_datetime(result["trade_date"], errors="coerce").dt.normalize()
        result = result.loc[dates.ne(trade_date.normalize())].copy()
    else:
        dates = pd.to_datetime(result.index, errors="coerce").normalize()
        result = result.loc[dates != trade_date.normalize()].copy()
        result = result.reset_index().rename(columns={result.index.name or "index": "trade_date"})
    row = {
        "stock_code": ticker,
        "trade_date": trade_date.normalize(),
        **numeric,
    }
    result = pd.concat([result, DataFrame([row])], ignore_index=True, sort=False)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result = result.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    return result, True


def _investor_frames(raw: DataFrame) -> dict[str, DataFrame]:
    metadata = dict(getattr(raw, "attrs", {})) if raw is not None else {}

    def empty() -> DataFrame:
        frame = DataFrame(
            columns=["institution", "foreign", "individual"],
            index=pd.DatetimeIndex([], name="trade_date"),
        )
        frame.attrs.update(metadata)
        return frame
    if raw is None or raw.empty or not {"trade_date", "investor_type"}.issubset(raw.columns):
        return {timeframe: empty() for timeframe in TIMEFRAME_LABELS}

    clean = raw.copy()
    clean["trade_date"] = pd.to_datetime(clean["trade_date"], errors="coerce")

    def safe_code(value: object) -> str | None:
        try:
            return normalize_investor_code(str(value))
        except (TypeError, ValueError):
            return None

    clean["investor_type"] = clean["investor_type"].map(safe_code)
    clean = clean.loc[
        clean["trade_date"].notna() & clean["investor_type"].notna()
    ].copy()
    if clean.empty:
        return {timeframe: empty() for timeframe in TIMEFRAME_LABELS}

    output: dict[str, DataFrame] = {}
    for timeframe in TIMEFRAME_LABELS:
        aggregated = aggregate_investor_flow(clean, timeframe, include_totals=True)
        if aggregated.empty:
            output[timeframe] = empty()
            continue
        selected = aggregated.loc[
            aggregated["investor_type"].isin(
                ["INSTITUTION_TOTAL", "FOREIGN_TOTAL", "INDIVIDUAL"]
            )
        ]
        pivot = selected.pivot_table(
            index="trade_date",
            columns="investor_type",
            values="net_value",
            aggfunc="sum",
            fill_value=0,
        ).rename(
            columns={
                "INSTITUTION_TOTAL": "institution",
                "FOREIGN_TOTAL": "foreign",
                "INDIVIDUAL": "individual",
            }
        )
        for column in ("institution", "foreign", "individual"):
            if column not in pivot:
                # Keep an entirely unavailable category distinct from a true
                # zero net flow on a date for which that category was supplied.
                pivot[column] = np.nan
        pivot.index = pd.DatetimeIndex(pd.to_datetime(pivot.index), name="trade_date")
        result = pivot[
            ["institution", "foreign", "individual"]
        ].sort_index()
        result.attrs.update(metadata)
        output[timeframe] = result
    return output


class PostgreSQLOnDemandData:
    """Thread-safe GUI facade over the PostgreSQL fact tables."""

    def __init__(
        self,
        target: PostgreSQLSettings,
        *,
        cache_seconds: int = SCREEN_CACHE_SECONDS,
    ) -> None:
        self.target = target
        self.settings = settings_from_database_target(target)
        self.cache_seconds = max(0, int(cache_seconds))
        self._screen_cache: dict[tuple[object, ...], tuple[float, OnDemandScreenResult]] = {}
        self._master_cache: tuple[float, DataFrame] | None = None
        self._investor_cache: dict[str, tuple[float, DataFrame]] = {}
        self._chart_raw_cache: dict[str, tuple[float, DataFrame]] = {}
        self._chart_frame_cache: dict[
            tuple[str, str], tuple[float, DataFrame]
        ] = {}
        self._security_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    def _master(self, repository: BaseDataRepository) -> DataFrame:
        now = self._now()
        with self._lock:
            cached = self._master_cache
            if cached is not None and now - cached[0] <= self.cache_seconds:
                return cached[1].copy(deep=True)
        frame = repository.get_security_master_frame()
        with self._lock:
            self._master_cache = (now, frame.copy(deep=True))
        return frame

    def _screen_cache_get(
        self,
        key: tuple[object, ...],
        now: float,
    ) -> OnDemandScreenResult | None:
        with self._lock:
            cached = self._screen_cache.get(key)
            if cached is None or now - cached[0] > self.cache_seconds:
                return None
            return cached[1]

    def _screen_cache_set(
        self,
        key: tuple[object, ...],
        now: float,
        value: OnDemandScreenResult,
    ) -> None:
        with self._lock:
            self._screen_cache[key] = (now, value)

    def _trim_chart_cache_locked(self) -> None:
        """Keep chart reuse useful without retaining every visited stock."""

        while len(self._chart_raw_cache) > CHART_CACHE_MAX_TICKERS:
            oldest_code = next(iter(self._chart_raw_cache))
            self._chart_raw_cache.pop(oldest_code, None)
            self._security_cache.pop(oldest_code, None)
            self._investor_cache.pop(oldest_code, None)
            for cache_key in tuple(self._chart_frame_cache):
                if cache_key[0] == oldest_code:
                    self._chart_frame_cache.pop(cache_key, None)

    def resolve_ticker(self, ticker_or_name: object) -> str:
        query = str(ticker_or_name).strip()
        if not query:
            raise ValueError("종목명 또는 6자리 종목코드를 입력하세요.")
        if query.isdigit():
            return query.zfill(6)
        with BaseDataRepository(self.settings) as repository:
            master = self._master(repository)
        matches = master.loc[
            master["stock_name"].fillna("").astype(str).str.casefold().eq(query.casefold())
        ]
        if matches.empty:
            raise ValueError(f"종목명 '{query}'을 종목 마스터에서 찾을 수 없습니다.")
        if len(matches) > 1:
            codes = ", ".join(matches["stock_code"].astype(str).tolist())
            raise ValueError(f"종목명 '{query}'이 여러 종목과 일치합니다: {codes}")
        return str(matches.iloc[0]["stock_code"]).zfill(6)

    def load_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None = None,
        comparison_ticker: str = "222800",
        venue: str = "KRX",
        cancel_event: threading.Event | None = None,
    ) -> OnDemandScreenResult:
        requested = None if as_of_date is None else pd.Timestamp(as_of_date).date()
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        _raise_if_cancelled(cancel_event)
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date() if venue == "KRX" else repository.latest_venue_ohlcv_date(venue)
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            end_date = min(latest, requested) if requested is not None else latest
            cache_key = (venue, screen_type, end_date)
            now = self._now()
            value = self._screen_cache_get(cache_key, now)
            if value is not None:
                return OnDemandScreenResult(
                    rows=value.rows.copy(deep=True),
                    as_of_date=value.as_of_date,
                    universe_count=value.universe_count,
                )
            lookback = SCREEN_LOOKBACK_DAYS[screen_type]
            start_date = end_date - dt.timedelta(days=lookback)
            raw = repository.get_market_ohlcv(start_date, end_date) if venue == "KRX" else repository.get_venue_ohlcv(venue, start_date, end_date)
            _raise_if_cancelled(cancel_event)
            history, actual_date = _prepare_history(raw, self._master(repository))
            if requested is not None and actual_date != requested:
                raise ValueError(
                    f"선택한 {requested.isoformat()} 자료가 완전하지 않습니다. "
                    f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                )
            rows = calculate_screen(
                history,
                screen_type,
                comparison_ticker=comparison_ticker,
            )
            _raise_if_cancelled(cancel_event)
            universe_count = int(history.loc[
                history["trade_date"].dt.date.eq(actual_date), "ticker"
            ].nunique())
            value = OnDemandScreenResult(rows, actual_date, universe_count)
            self._screen_cache_set(cache_key, now, value)
            return OnDemandScreenResult(
                rows=rows.copy(deep=True),
                as_of_date=actual_date,
                universe_count=universe_count,
            )

    def load_screen_period(
        self,
        screen_type: str,
        as_of_dates: list[dt.date] | tuple[dt.date, ...],
        *,
        comparison_ticker: str = "222800",
        venue: str = "KRX",
        cancel_event: threading.Event | None = None,
    ) -> list[OnDemandScreenResult]:
        """Calculate several dated screens from one PostgreSQL bulk read.

        Each snapshot is still calculated from its own bounded lookback so a
        later corporate action cannot leak into an earlier result.  The costly
        all-market SQL query and security-master query are shared by the whole
        request.
        """

        _raise_if_cancelled(cancel_event)
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        requested_dates = sorted(
            {pd.Timestamp(value).date() for value in as_of_dates}
        )
        if not requested_dates:
            return []
        if screen_type not in SCREEN_LOOKBACK_DAYS:
            raise ValueError(f"지원하지 않는 스크리닝: {screen_type}")

        lookback = SCREEN_LOOKBACK_DAYS[screen_type]
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date() if venue == "KRX" else repository.latest_venue_ohlcv_date(venue)
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            if requested_dates[-1] > latest:
                raise ValueError(
                    f"선택한 {requested_dates[-1].isoformat()} 자료가 없습니다. "
                    f"PostgreSQL 최신 기준일은 {latest.isoformat()}입니다."
                )

            now = self._now()
            cached_results: dict[dt.date, OnDemandScreenResult] = {}
            missing_dates: list[dt.date] = []
            for screen_date in requested_dates:
                cached = self._screen_cache_get((venue, screen_type, screen_date), now)
                if cached is not None:
                    cached_results[screen_date] = cached
                else:
                    missing_dates.append(screen_date)

            if missing_dates:
                raw_start = missing_dates[0] - dt.timedelta(days=lookback)
                raw_end = missing_dates[-1]
                raw = repository.get_market_ohlcv(raw_start, raw_end) if venue == "KRX" else repository.get_venue_ohlcv(venue, raw_start, raw_end)
                _raise_if_cancelled(cancel_event)
                if raw.empty:
                    raise ValueError("선택 기간의 PostgreSQL 일봉 원천자료가 없습니다.")
                raw_dates = pd.to_datetime(raw["trade_date"], errors="coerce").dt.date
                master = self._master(repository)

                for screen_date in missing_dates:
                    _raise_if_cancelled(cancel_event)
                    window_start = screen_date - dt.timedelta(days=lookback)
                    window_mask = raw_dates.between(window_start, screen_date)
                    history, actual_date = _prepare_history(
                        raw.loc[window_mask].copy(),
                        master,
                    )
                    if actual_date != screen_date:
                        raise ValueError(
                            f"선택한 {screen_date.isoformat()} 자료가 완전하지 않습니다. "
                            f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                        )
                    rows = calculate_screen(
                        history,
                        screen_type,
                        comparison_ticker=comparison_ticker,
                    )
                    _raise_if_cancelled(cancel_event)
                    universe_count = int(
                        history.loc[
                            history["trade_date"].dt.date.eq(actual_date),
                            "ticker",
                        ].nunique()
                    )
                    value = OnDemandScreenResult(rows, actual_date, universe_count)
                    self._screen_cache_set(
                        (venue, screen_type, screen_date), now, value
                    )
                    cached_results[screen_date] = value

        return [
            OnDemandScreenResult(
                rows=cached_results[screen_date].rows.copy(deep=True),
                as_of_date=cached_results[screen_date].as_of_date,
                universe_count=cached_results[screen_date].universe_count,
            )
            for screen_date in requested_dates
        ]

    def load_overlay_snapshot(
        self,
        *,
        as_of_date: object | None = None,
        venue: str = "KRX",
    ) -> OnDemandScreenResult:
        """Return all calculated fields required by the real-time radio mode."""

        requested = None if as_of_date is None else pd.Timestamp(as_of_date).date()
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date() if venue == "KRX" else repository.latest_venue_ohlcv_date(venue)
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            end_date = min(latest, requested) if requested is not None else latest
            cache_key = (venue, "__overlay__", end_date)
            now = self._now()
            value = self._screen_cache_get(cache_key, now)
            if value is not None:
                return OnDemandScreenResult(
                    value.rows.copy(deep=True),
                    value.as_of_date,
                    value.universe_count,
                )
            start = end_date - dt.timedelta(days=SCREEN_LOOKBACK_DAYS["ema_similarity"])
            raw = repository.get_market_ohlcv(start, end_date) if venue == "KRX" else repository.get_venue_ohlcv(venue, start, end_date)
            history, actual_date = _prepare_history(raw, self._master(repository))
            if requested is not None and actual_date != requested:
                raise ValueError(
                    f"선택한 {requested.isoformat()} 자료가 완전하지 않습니다. "
                    f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                )
            rows = build_overlay_snapshot(history)
            universe_count = len(rows)
            value = OnDemandScreenResult(rows, actual_date, universe_count)
            self._screen_cache_set(cache_key, now, value)
            return OnDemandScreenResult(
                rows.copy(deep=True),
                actual_date,
                universe_count,
            )

    def load_overlay_period(
        self,
        as_of_dates: list[dt.date] | tuple[dt.date, ...],
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[OnDemandScreenResult]:
        """Build full dated cross-sections from one shared PostgreSQL read."""

        _raise_if_cancelled(cancel_event)
        requested_dates = sorted(
            {pd.Timestamp(value).date() for value in as_of_dates}
        )
        if not requested_dates:
            return []
        with BaseDataRepository(self.settings) as repository:
            latest = repository.latest_ohlcv_date()
            if latest is None:
                raise ValueError("PostgreSQL에 일봉 원천자료가 없습니다.")
            if requested_dates[-1] > latest:
                raise ValueError(
                    f"선택한 {requested_dates[-1].isoformat()} 자료가 없습니다. "
                    f"PostgreSQL 최신 기준일은 {latest.isoformat()}입니다."
                )

            now = self._now()
            cached_results: dict[dt.date, OnDemandScreenResult] = {}
            missing_dates: list[dt.date] = []
            for screen_date in requested_dates:
                cached = self._screen_cache_get(("__overlay__", screen_date), now)
                if cached is None:
                    missing_dates.append(screen_date)
                else:
                    cached_results[screen_date] = cached

            if missing_dates:
                lookback = SCREEN_LOOKBACK_DAYS["ema_similarity"]
                raw_start = missing_dates[0] - dt.timedelta(days=lookback)
                raw = repository.get_market_ohlcv(raw_start, missing_dates[-1])
                _raise_if_cancelled(cancel_event)
                if raw.empty:
                    raise ValueError("선택 기간의 PostgreSQL 일봉 원천자료가 없습니다.")
                raw_dates = pd.to_datetime(raw["trade_date"], errors="coerce").dt.date
                master = self._master(repository)
                for screen_date in missing_dates:
                    _raise_if_cancelled(cancel_event)
                    window_start = screen_date - dt.timedelta(days=lookback)
                    window_mask = raw_dates.between(window_start, screen_date)
                    history, actual_date = _prepare_history(
                        raw.loc[window_mask].copy(),
                        master,
                    )
                    if actual_date != screen_date:
                        raise ValueError(
                            f"선택한 {screen_date.isoformat()} 자료가 완전하지 않습니다. "
                            f"실제 계산 가능 기준일은 {actual_date.isoformat()}입니다."
                        )
                    rows = build_overlay_snapshot(history)
                    _raise_if_cancelled(cancel_event)
                    value = OnDemandScreenResult(rows, actual_date, len(rows))
                    self._screen_cache_set(("__overlay__", screen_date), now, value)
                    cached_results[screen_date] = value

        return [
            OnDemandScreenResult(
                rows=cached_results[screen_date].rows.copy(deep=True),
                as_of_date=cached_results[screen_date].as_of_date,
                universe_count=cached_results[screen_date].universe_count,
            )
            for screen_date in requested_dates
        ]

    def load_chart(
        self,
        ticker_or_name: object,
        *,
        timeframes: tuple[str, ...] = ("D", "W"),
        include_investor: bool = False,
        live_bar: dict[str, object] | None = None,
        venue: str = "KRX",
        cancel_event: threading.Event | None = None,
    ) -> OnDemandChartResult:
        """Load only requested chart components with short-lived reusable caches."""

        _raise_if_cancelled(cancel_event)
        code = self.resolve_ticker(ticker_or_name)
        venue = str(venue).strip().upper()
        if venue not in DATABASE_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue!r}")
        cache_code = f"{venue}:{code}"
        selected_timeframes = tuple(
            dict.fromkeys(str(value).strip().upper() for value in timeframes)
        )
        invalid = [value for value in selected_timeframes if value not in TIMEFRAME_LABELS]
        if invalid:
            raise ValueError(f"지원하지 않는 봉 주기: {invalid[0]!r}")
        now = self._now()
        with self._lock:
            cached_raw = self._chart_raw_cache.get(cache_code)
            raw = (
                cached_raw[1].copy(deep=True)
                if cached_raw is not None
                and now - cached_raw[0] <= CHART_CACHE_SECONDS
                else None
            )
            cached_security = self._security_cache.get(cache_code)
            security_row = (
                dict(cached_security[1])
                if cached_security is not None
                and now - cached_security[0] <= CHART_CACHE_SECONDS
                else None
            )
            cached_investor = self._investor_cache.get(cache_code)
            investor_raw = (
                cached_investor[1].copy(deep=True)
                if include_investor
                and cached_investor is not None
                and now - cached_investor[0] <= NAVER_INVESTOR_CACHE_SECONDS
                else None
            )

        needs_database = (
            raw is None
            or security_row is None
            or (include_investor and investor_raw is None)
        )
        if needs_database:
            with BaseDataRepository(self.settings) as repository:
                if raw is None:
                    if venue == "KRX":
                        raw = repository.get_ohlcv(code)
                    else:
                        raw = repository.get_venue_ohlcv(venue, ticker=code)
                    if raw.empty:
                        raise ValueError(f"{code}의 {venue} 일봉 원천자료가 없습니다.")
                if security_row is None:
                    master = self._master(repository)
                    security = master.loc[
                        master["stock_code"].astype(str).eq(code)
                    ]
                    security_row = (
                        security.iloc[0].to_dict() if not security.empty else {}
                    )
                if include_investor and investor_raw is None:
                    investor_raw = repository.get_investor_flow(code)
            _raise_if_cancelled(cancel_event)
            with self._lock:
                self._chart_raw_cache.pop(cache_code, None)
                self._chart_raw_cache[cache_code] = (now, raw.copy(deep=True))
                self._security_cache[cache_code] = (now, dict(security_row or {}))
                self._trim_chart_cache_locked()

        if raw is None:
            raise ValueError(f"{code}의 PostgreSQL 일봉 원천자료가 없습니다.")
        if include_investor and investor_raw is not None and investor_raw.empty:
            investor_raw.attrs = {
                "source": "LS:SOURCE_PENDING_NORMALIZATION",
                "source_label": "LS 화면용 수급 미적재",
                "source_error": "LS 원본은 별도 저장됩니다. 금액 단위·투자자 코드 검증 전에는 화면용 수급으로 사용하지 않습니다.",
            }
        elif include_investor and investor_raw is not None:
            sources = []
            if "source" in investor_raw:
                sources = sorted(
                    investor_raw["source"].dropna().astype(str).unique().tolist()
                )
            investor_raw.attrs.update(
                {
                    "source": ", ".join(sources) or "PostgreSQL",
                    "source_label": investor_raw.attrs.get("source_label", "PostgreSQL 저장 수급 원천"),
                    "estimated_value": investor_raw.attrs.get("estimated_value", False),
                }
            )
        if include_investor and investor_raw is not None:
            with self._lock:
                self._investor_cache[cache_code] = (
                    now,
                    investor_raw.copy(deep=True),
                )

        chart_raw, has_live_bar = _append_live_chart_bar(raw, code, live_bar)
        bars: dict[str, DataFrame] = {}
        for timeframe in selected_timeframes:
            _raise_if_cancelled(cancel_event)
            cache_key = (cache_code, timeframe)
            with self._lock:
                cached_frame = None if has_live_bar else self._chart_frame_cache.get(cache_key)
                frame = (
                    cached_frame[1].copy(deep=True)
                    if cached_frame is not None
                    and now - cached_frame[0] <= CHART_CACHE_SECONDS
                    else None
                )
            if frame is None:
                frame = build_chart_frame(chart_raw, timeframe)
                if not has_live_bar:
                    with self._lock:
                        self._chart_frame_cache[cache_key] = (
                            now,
                            frame.copy(deep=True),
                        )
            bars[timeframe] = frame
        _raise_if_cancelled(cancel_event)
        row = security_row or {}

        def text_value(key: str, fallback: str = "") -> str:
            value = row.get(key) if hasattr(row, "get") else None
            return fallback if value is None or pd.isna(value) else str(value)

        return OnDemandChartResult(
            ticker=code,
            name=text_value("stock_name", code),
            market=text_value("market"),
            industry=text_value("industry"),
            bars=bars,
            investor=(
                _investor_frames(investor_raw)
                if include_investor and investor_raw is not None
                else {}
            ),
        )


__all__ = [
    "OnDemandChartResult",
    "OnDemandScreenResult",
    "PostgreSQLOnDemandData",
    "CHART_CACHE_MAX_TICKERS",
    "CHART_CACHE_SECONDS",
    "SCREEN_CACHE_SECONDS",
    "TIMEFRAME_LABELS",
    "build_overlay_snapshot",
    "calculate_screen",
    "fetch_naver_investor_trend",
]
