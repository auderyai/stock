"""Read-only workstation repository and data-transfer models."""

from __future__ import annotations

import datetime as dt
import io
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas import DataFrame

from krx_research.analytics import (
    EMA_WINDOWS,
    build_market_screens,
    calculate_technical_indicators,
    exclude_spac_securities,
)
from krx_research.analytics.indicators import exponential_rsi
from krx_research.collectors.index_membership import (
    INDEX_GAINER_DEFINITIONS,
    IndexMembership,
    fetch_index_membership,
)
from krx_research.collectors.market_data import normalize_ticker
from krx_research.collectors.realtime_quotes import (
    QUOTE_VENUE_KRX,
    QUOTE_VENUES,
    RealtimeQuoteSnapshot,
    fetch_realtime_krx_quotes,
)
from krx_research.database import (
    DatabaseTarget,
    PostgreSQLSettings,
    open_research_store,
)
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY
from krx_research.policies.screen_catalog import (
    DIRECT_ON_DEMAND_SCREEN_TYPES,
    INDEX_MEMBERSHIP_TYPES,
    INDEX_RELATED_SCREEN_TYPES,
    INDEX_WEEKLY_SCREEN_TYPES,
    INVESTOR_FLOW_SCREEN_DEFINITIONS,
    INVESTOR_FLOW_SCREEN_TYPES,
    MARKET_RESULT_DEFINITIONS,
    MARKET_RESULT_SCREEN_TYPES,
    MARKET_TRADING_VALUE_SCREEN_TYPES,
    MARKET_WEEKLY_GAINER_SCREEN_TYPES,
    WEEKLY_TRADING_VALUE_SCREEN_TYPES,
)
from krx_research.policies.workstation_options import (
    DATABASE_SOURCE_MODE, DATA_SOURCE_MODES, REALTIME_SOURCE_MODE,
)
from krx_research.models.workstation import ChartDataset, ScreenDataset
from krx_research.analytics.screening import (
    _market_values,
    build_index_gainer_rows,
    build_index_weekly_gainer_rows,
    build_investor_flow_rows,
    build_market_result_rows,
    overlay_realtime_quotes,
    select_period_screen_dates,
)

from .on_demand_repository import PostgreSQLOnDemandData

class DatabaseDateMismatchError(ValueError):
    """The selected screening date has not been recorded in the database."""

REALTIME_CACHE_SECONDS = 60.0
RSI_PERIOD, RSI_SIGNAL_PERIOD = DEFAULT_CHART_ANALYSIS_POLICY.rsi.periods
STOCHASTIC_K_PERIOD, STOCHASTIC_K_SMOOTHING, STOCHASTIC_D_PERIOD = (
    DEFAULT_CHART_ANALYSIS_POLICY.stochastic_slow.periods
)
KST = ZoneInfo("Asia/Seoul")


class WorkstationData:
    """Open short-lived readers so chart workers never share connections."""

    def __init__(
        self,
        database_target: DatabaseTarget,
        *,
        index_membership_fetcher: Callable[[str, object], IndexMembership] = (
            fetch_index_membership
        ),
        realtime_quote_fetcher: Callable[..., RealtimeQuoteSnapshot] = (
            fetch_realtime_krx_quotes
        ),
        realtime_cache_seconds: float = REALTIME_CACHE_SECONDS,
    ) -> None:
        if realtime_cache_seconds < 0:
            raise ValueError("realtime_cache_seconds must not be negative")
        self.database_target = database_target
        self.index_membership_fetcher = index_membership_fetcher
        self.realtime_quote_fetcher = realtime_quote_fetcher
        self.realtime_cache_seconds = float(realtime_cache_seconds)
        self._index_membership_cache: dict[tuple[str, dt.date], IndexMembership] = {}
        self._realtime_cache: tuple[
            str,
            float,
            RealtimeQuoteSnapshot,
            DataFrame,
            dt.date,
        ] | None = None
        self._realtime_cache_lock = threading.Lock()
        self._on_demand = (
            PostgreSQLOnDemandData(database_target)
            if isinstance(database_target, PostgreSQLSettings)
            else None
        )


    def available_screen_dates(
        self, limit: int = 500, *, quote_venue: str = QUOTE_VENUE_KRX
    ) -> list[dt.date]:
        """Return selectable PostgreSQL trading dates, newest first."""

        if self._on_demand is not None:
            with BaseDataRepository(self._on_demand.settings) as repository:
                if quote_venue != QUOTE_VENUE_KRX:
                    return repository.available_venue_ohlcv_dates(quote_venue, limit=limit)
                return repository.available_ohlcv_dates(
                    adjusted_only=True,
                    limit=limit,
                )
        with open_research_store(self.database_target, read_only=True) as store:
            method = getattr(store, "available_ohlcv_dates", None)
            if callable(method):
                return list(method(adjusted_only=True, limit=limit))
            latest = store.latest_adjusted_ohlcv_date()
        return [] if latest is None else [latest]

    def latest_screen_date(self, *, quote_venue: str = QUOTE_VENUE_KRX) -> dt.date | None:
        """Return a usable default even when the distinct-date list fails."""

        if self._on_demand is not None:
            with BaseDataRepository(self._on_demand.settings) as repository:
                if quote_venue != QUOTE_VENUE_KRX:
                    return repository.latest_venue_ohlcv_date(quote_venue)
                return repository.latest_ohlcv_date()
        with open_research_store(self.database_target, read_only=True) as store:
            method = getattr(store, "latest_adjusted_ohlcv_date", None)
            return method() if callable(method) else None

    def load_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None = None,
        data_source_mode: str = DATABASE_SOURCE_MODE,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
        comparison_ticker: str | None = None,
    ) -> ScreenDataset:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()
        if screen_type not in SCREEN_TITLES:
            raise ValueError(f"Unsupported screen type: {screen_type!r}")
        if data_source_mode not in DATA_SOURCE_MODES:
            raise ValueError(f"Unsupported data source mode: {data_source_mode!r}")
        quote_venue = str(quote_venue).strip().upper()
        if quote_venue not in QUOTE_VENUES:
            raise ValueError(f"Unsupported quote venue: {quote_venue!r}")
        if screen_type == "ema_similarity":
            data_source_mode = DATABASE_SOURCE_MODE
        if screen_type in INVESTOR_FLOW_SCREEN_TYPES:
            if data_source_mode != DATABASE_SOURCE_MODE:
                raise ValueError("수급 거래대금은 DB에 저장된 확정 수급자료로 조회하십시오.")
            return self._load_investor_flow_screen(screen_type, as_of_date=as_of_date)
        if screen_type == "near_high_52w" and self._on_demand is None:
            raise ValueError("52주 고가 대비 종가 검색에는 PostgreSQL 일봉 원천자료가 필요합니다.")
        if data_source_mode == REALTIME_SOURCE_MODE and screen_type in WEEKLY_TRADING_VALUE_SCREEN_TYPES:
            raise ValueError("주간 거래대금 순위는 PostgreSQL 데이터베이스 모드에서 조회하십시오.")
        if data_source_mode == REALTIME_SOURCE_MODE:
            result = self._load_realtime_screen(
                screen_type,
                as_of_date=as_of_date,
                quote_venue=quote_venue,
            )
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            return result
        if self._on_demand is not None and screen_type in DIRECT_ON_DEMAND_SCREEN_TYPES:
            return self._load_on_demand_screen(
                screen_type,
                as_of_date=as_of_date,
                quote_venue=quote_venue,
                cancel_event=cancel_event,
                comparison_ticker=comparison_ticker,
            )
        if screen_type in MARKET_RESULT_SCREEN_TYPES:
            return self._load_database_market_gainer_screen(
                screen_type,
                as_of_date=as_of_date,
            )
        if screen_type in INDEX_RELATED_SCREEN_TYPES:
            return self._load_index_gainer_screen(
                screen_type,
                as_of_date=as_of_date,
            )
        with open_research_store(self.database_target, read_only=True) as store:
            rows = store.get_screen_results(screen_type, as_of_date=as_of_date)
            latest_price_date = store.latest_adjusted_ohlcv_date()
            latest_indicator_date = store.latest_technical_indicator_date()
        run = rows.attrs.get("screen_run")
        if run is None:
            raise ValueError("저장된 스크리닝 결과가 없습니다. 일일 파이프라인을 먼저 실행하세요.")
        rows = exclude_spac_securities(rows)
        run_details = dict(run)
        run_details["source"] = "DATABASE"
        run_details["data_source_mode"] = DATABASE_SOURCE_MODE
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run_details,
            rows=rows,
            latest_price_date=latest_price_date,
            latest_indicator_date=latest_indicator_date,
        )

    def load_screen_period(
        self,
        screen_type: str,
        *,
        start_date: object | None,
        end_date: object | None,
        data_source_mode: str = DATABASE_SOURCE_MODE,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
        comparison_ticker: str | None = None,
    ) -> ScreenDataset:
        """Load one or more stored trading dates and preserve each row's date."""

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()
        start = pd.Timestamp(start_date).date() if start_date is not None else None
        end = pd.Timestamp(end_date).date() if end_date is not None else None
        cancel_options: dict[str, object] = (
            {"cancel_event": cancel_event} if cancel_event is not None else {}
        )
        if start is None and end is None:
            dataset = self.load_screen(
                screen_type,
                as_of_date=None,
                data_source_mode=data_source_mode,
                quote_venue=quote_venue,
                comparison_ticker=comparison_ticker,
                **cancel_options,
            )
            rows = dataset.rows.copy()
            rows["screen_date"] = str(dataset.run.get("as_of_date", ""))
            return replace(dataset, rows=rows)
        start = start or end
        end = end or start
        if start is None or end is None:
            raise ValueError("조회 시작일과 종료일을 입력하십시오.")
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        if data_source_mode == REALTIME_SOURCE_MODE:
            # A current quote provider legitimately returns the computer's
            # current KST trading date.  Never constrain it with a stale DB
            # date left in the GUI selectors.
            today = dt.datetime.now(tz=KST).date()
            start = today
            end = today
        if screen_type in INVESTOR_FLOW_SCREEN_TYPES and data_source_mode != DATABASE_SOURCE_MODE:
            raise ValueError("수급 거래대금은 데이터베이스 모드에서 조회하십시오.")
        if data_source_mode == DATABASE_SOURCE_MODE:
            latest = self.latest_screen_date(quote_venue=quote_venue)
            if latest is None:
                raise DatabaseDateMismatchError(
                    "DB에 저장된 일봉 날짜가 없습니다. DB 갱신 후 조회 날짜를 다시 선택하세요."
                )
            if end > latest:
                raise DatabaseDateMismatchError(
                    f"선택한 종료일 {end.isoformat()}은 DB 마지막 갱신일 "
                    f"{latest.isoformat()}보다 늦습니다. 조회 날짜를 수정하거나 DB를 갱신하세요."
                )
        if start == end:
            dataset = self.load_screen(
                screen_type,
                as_of_date=end,
                data_source_mode=data_source_mode,
                quote_venue=quote_venue,
                comparison_ticker=comparison_ticker,
                **cancel_options,
            )
            rows = dataset.rows.copy()
            rows["screen_date"] = end.isoformat()
            run = dict(dataset.run)
            run.update(
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                date_count=1,
            )
            return replace(dataset, run=run, rows=rows)

        available = self.available_screen_dates(limit=5000, quote_venue=quote_venue)
        selected = select_period_screen_dates(
            available,
            start=start,
            end=end,
            screen_type=screen_type,
        )
        if not selected:
            raise ValueError("선택 기간에 저장된 영업일 자료가 없습니다.")
        datasets: list[ScreenDataset] = []
        frames: list[DataFrame] = []
        on_demand = getattr(self, "_on_demand", None)
        if on_demand is not None and screen_type not in INVESTOR_FLOW_SCREEN_TYPES:
            load_options: dict[str, object] = {}
            if cancel_event is not None:
                load_options["cancel_event"] = cancel_event
            if screen_type in DIRECT_ON_DEMAND_SCREEN_TYPES:
                computed_results = on_demand.load_screen_period(
                    screen_type,
                    selected,
                    comparison_ticker=comparison_ticker or "222800",
                    venue=quote_venue,
                    **load_options,
                )
            else:
                computed_results = on_demand.load_overlay_period(
                    selected,
                    **load_options,
                )
            period_membership = None
            if screen_type in INDEX_RELATED_SCREEN_TYPES and computed_results:
                newest = computed_results[-1]
                period_membership = self._membership_for_screen(
                    screen_type,
                    newest.as_of_date,
                    newest.rows,
                )
            source_datasets = [
                self._screen_dataset_from_on_demand(
                    screen_type,
                    computed,
                    quote_venue=quote_venue,
                    **(
                        {"membership": period_membership}
                        if period_membership is not None
                        else {}
                    ),
                )
                for computed in computed_results
            ]
        else:
            source_datasets = [
                self.load_screen(
                    screen_type,
                    as_of_date=screen_date,
                    data_source_mode=DATABASE_SOURCE_MODE,
                    comparison_ticker=comparison_ticker,
                )
                for screen_date in selected
            ]
        for screen_date, dataset in zip(selected, source_datasets, strict=True):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            frame = dataset.rows.copy()
            frame["screen_date"] = screen_date.isoformat()
            frames.append(frame)
            datasets.append(dataset)
        rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        newest = datasets[-1]
        run = dict(newest.run)
        run.update(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            date_count=len(selected),
            as_of_date=selected[-1].isoformat(),
            data_source_mode=DATABASE_SOURCE_MODE,
        )
        price_dates = [item.latest_price_date for item in datasets if item.latest_price_date]
        indicator_dates = [
            item.latest_indicator_date for item in datasets if item.latest_indicator_date
        ]
        return ScreenDataset(
            screen_type=screen_type,
            title=newest.title,
            run=run,
            rows=rows,
            latest_price_date=max(price_dates) if price_dates else None,
            latest_indicator_date=max(indicator_dates) if indicator_dates else None,
        )

    def _load_on_demand_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
        comparison_ticker: str | None = None,
    ) -> ScreenDataset:
        if self._on_demand is None:
            raise RuntimeError("PostgreSQL 온디맨드 엔진이 초기화되지 않았습니다.")
        computed = self._on_demand.load_screen(
            screen_type,
            as_of_date=as_of_date,
            venue=quote_venue,
            cancel_event=cancel_event,
            comparison_ticker=comparison_ticker or "222800",
        )
        return self._screen_dataset_from_on_demand(
            screen_type, computed, quote_venue=quote_venue
        )

    def _screen_dataset_from_on_demand(
        self,
        screen_type: str,
        computed: Any,
        *,
        membership: IndexMembership | None = None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> ScreenDataset:
        # LS_SCREEN_REPAIR_V2_ACTUAL_GUI_PATH
        if self._on_demand is not None and screen_type in (MARKET_RESULT_SCREEN_TYPES | INDEX_RELATED_SCREEN_TYPES):
            from krx_research.data_engine.screen_coverage import validate_screen_coverage
            markets = (MARKET_RESULT_DEFINITIONS[screen_type] if screen_type in MARKET_RESULT_SCREEN_TYPES
                       else self._index_market(screen_type)).split('+')
            minimum = 100 if screen_type in MARKET_TRADING_VALUE_SCREEN_TYPES else 50 if screen_type in MARKET_RESULT_SCREEN_TYPES or screen_type == 'kospi200_kosdaq150_daily_gainers' else 30
            with BaseDataRepository(self._on_demand.settings) as repository:
                validate_screen_coverage(repository, computed.as_of_date, computed.rows, markets, minimum=minimum)
            if screen_type in INDEX_RELATED_SCREEN_TYPES:
                membership = membership or self._membership_for_screen(screen_type, computed.as_of_date, computed.rows)
                with BaseDataRepository(self._on_demand.settings) as repository:
                    validate_screen_coverage(repository, computed.as_of_date, computed.rows, markets, membership, minimum)
        rows = computed.rows
        market = "ALL"
        matched_count = computed.universe_count
        constituent_count = computed.universe_count
        extra: dict[str, Any] = {}
        if screen_type in MARKET_RESULT_SCREEN_TYPES:
            rows = build_market_result_rows(rows, screen_type)
            market = MARKET_RESULT_DEFINITIONS[screen_type]
            markets = _market_values(screen_type)
            constituent_count = int(
                computed.rows["market"]
                .astype("string")
                .str.upper()
                .str.strip()
                .isin(markets)
                .sum()
            )
            matched_count = constituent_count
        elif screen_type in INDEX_RELATED_SCREEN_TYPES:
            membership = membership or self._membership_for_screen(
                screen_type, computed.as_of_date, computed.rows
            )
            rows = (
                build_index_weekly_gainer_rows(computed.rows, membership)
                if screen_type in INDEX_WEEKLY_SCREEN_TYPES
                else build_index_gainer_rows(
                    computed.rows,
                    membership,
                    limit=max(1, len(snapshot)),
                )
            )
            market = self._index_market(screen_type)
            constituent_count = len(membership.tickers)
            matched_count = int(
                computed.rows["ticker"].astype(str).isin(membership.tickers).sum()
            )
            extra = {
                "membership_source": membership.source,
                "index_code": membership.index_code,
                "index_name": membership.index_name,
                "constituent_as_of_date": membership.as_of_date.isoformat(),
            }
        generated_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
        run = {
            "run_id": (
                f"on-demand:{screen_type}:{computed.as_of_date.isoformat()}"
            ),
            "as_of_date": computed.as_of_date.isoformat(),
            "generated_at": generated_at,
            "source": "POSTGRESQL_BASE_ON_DEMAND",
            "data_source_mode": DATABASE_SOURCE_MODE,
            "quote_venue": quote_venue,
            "market": market,
            "constituent_count": constituent_count,
            "matched_count": matched_count,
            "positive_count": self._positive_count(rows, screen_type),
            **extra,
        }
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=computed.as_of_date,
            latest_indicator_date=computed.as_of_date,
        )

    def _database_snapshot(
        self,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> tuple[DataFrame, dt.date, dt.date | None]:
        if self._on_demand is not None:
            computed = self._on_demand.load_overlay_snapshot(
                as_of_date=as_of_date,
                venue=quote_venue,
            )
            return (
                computed.rows,
                computed.as_of_date,
                computed.as_of_date,
            )
        with open_research_store(self.database_target, read_only=True) as store:
            latest_price_date = store.latest_adjusted_ohlcv_date()
            screen_date = (
                store.latest_technical_indicator_date()
                if as_of_date is None
                else store.latest_technical_indicator_date(on_or_before=as_of_date)
            )
            if screen_date is None:
                raise ValueError("저장된 기술지표가 없습니다. 일일 파이프라인을 먼저 실행하세요.")
            snapshot = store.get_screen_snapshot(screen_date)
        return snapshot, screen_date, latest_price_date

    def _load_database_market_gainer_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
    ) -> ScreenDataset:
        snapshot, screen_date, latest_price_date = self._database_snapshot(as_of_date)
        market = MARKET_RESULT_DEFINITIONS[screen_type]
        markets = _market_values(screen_type)
        eligible = exclude_spac_securities(snapshot)
        market_count = int(
            eligible["market"]
            .astype("string")
            .str.upper()
            .str.strip()
            .isin(markets)
            .sum()
        )
        minimum = 100
        if market_count < minimum:
            raise ValueError(
                f"{screen_date.isoformat()} {market} DB 일봉은 {market_count}종목뿐입니다. "
                "당일 자료 수집이 완료되지 않았으므로 Top 결과를 표시하지 않습니다. "
                "메뉴 2번 일봉 갱신 완료 후 다시 조회하세요."
            )
        rows = build_market_result_rows(snapshot, screen_type)
        run = {
            "run_id": f"database:{screen_type}:{screen_date.isoformat()}",
            "as_of_date": screen_date.isoformat(),
            "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
            "source": "DATABASE",
            "data_source_mode": DATABASE_SOURCE_MODE,
            "market": market,
            "constituent_count": market_count,
            "matched_count": market_count,
            "positive_count": self._positive_count(rows, screen_type),
        }
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=latest_price_date,
            latest_indicator_date=screen_date,
        )

    def _membership(self, screen_type: str, screen_date: dt.date) -> IndexMembership:
        cache_key = (screen_type, screen_date)
        membership = self._index_membership_cache.get(cache_key)
        if membership is None:
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                membership = self.index_membership_fetcher(screen_type, screen_date)
            if membership.screen_type != screen_type:
                raise ValueError("Index membership does not match the requested screen")
            self._index_membership_cache[cache_key] = membership
        return membership

    @staticmethod
    def _index_market(screen_type: str) -> str:
        membership_types = INDEX_MEMBERSHIP_TYPES.get(
            screen_type,
            (screen_type,),
        )
        markets = tuple(
            dict.fromkeys(
                INDEX_GAINER_DEFINITIONS[value].market for value in membership_types
            )
        )
        return "+".join(markets)

    @staticmethod
    def _positive_count(rows: DataFrame, screen_type: str) -> int:
        metric = (
            "distance_from_52w_high_pct"
            if screen_type == "near_high_52w"
            else "weekly_return_pct"
            if screen_type in (INDEX_WEEKLY_SCREEN_TYPES | MARKET_WEEKLY_GAINER_SCREEN_TYPES)
            else (
                "weekly_trading_value_eok"
                if screen_type in WEEKLY_TRADING_VALUE_SCREEN_TYPES
                else "estimated_trading_value"
                if screen_type in MARKET_TRADING_VALUE_SCREEN_TYPES
                else "daily_return_pct"
            )
        )
        values = pd.to_numeric(rows.get(metric), errors="coerce")
        return int(values.gt(0).sum())

    def _membership_for_screen(
        self,
        screen_type: str,
        screen_date: dt.date,
        snapshot: DataFrame,
    ) -> IndexMembership:
        membership_types = INDEX_MEMBERSHIP_TYPES.get(
            screen_type,
            (screen_type,),
        )
        memberships: list[IndexMembership] = []
        for membership_type in membership_types:
            try:
                membership = self._membership(membership_type, screen_date)
            except Exception as error:
                raise ValueError(
                    f"{INDEX_GAINER_DEFINITIONS[membership_type].display_name} "
                    f"정확한 구성종목 조회 실패: {error}"
                ) from error
            memberships.append(membership)
        if len(memberships) == 1 and memberships[0].screen_type == screen_type:
            return memberships[0]
        return IndexMembership(
            screen_type=screen_type,
            index_code="+".join(item.index_code for item in memberships),
            index_name="+".join(item.index_name for item in memberships),
            as_of_date=min(item.as_of_date for item in memberships),
            tickers=tuple(
                sorted({ticker for item in memberships for ticker in item.tickers})
            ),
            source=" + ".join(item.source for item in memberships),
        )

    @staticmethod
    def _market_cap_proxy_membership(
        screen_type: str,
        screen_date: dt.date,
        snapshot: DataFrame,
    ) -> IndexMembership:
        """Last-resort, explicitly labelled proxy when public index APIs are unavailable."""

        definition = INDEX_GAINER_DEFINITIONS[screen_type]
        required = {"ticker", "market", "market_cap"}
        if missing := required.difference(snapshot.columns):
            raise ValueError(f"DB 지수 대체자료 필수 열이 없습니다: {sorted(missing)}")
        frame = exclude_spac_securities(snapshot).copy()
        frame["market"] = frame["market"].astype("string").str.upper().str.strip()
        frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
        frame = frame.loc[
            frame["market"].eq(definition.market) & frame["market_cap"].gt(0)
        ].sort_values(["market_cap", "ticker"], ascending=[False, True])
        minimum = max(30, int(definition.expected_count * 0.75))
        if len(frame) < minimum:
            raise ValueError(
                f"{definition.display_name} 공개 구성종목과 DB 시가총액 대체자료를 모두 "
                "확보하지 못했습니다."
            )
        tickers = tuple(frame.head(definition.expected_count)["ticker"].astype(str).str.zfill(6))
        return IndexMembership(
            screen_type=screen_type,
            index_code=definition.known_pykrx_code,
            index_name=f"{definition.display_name} (DB 시총 상위 대체)",
            as_of_date=screen_date,
            tickers=tickers,
            source="DATABASE:MARKET_CAP_PROXY",
        )

    def _load_investor_flow_screen(
        self, screen_type: str, *, as_of_date: object | None,
    ) -> ScreenDataset:
        if self._on_demand is None:
            raise ValueError("수급 거래대금 조회에는 PostgreSQL 수급 원천자료가 필요합니다.")
        with BaseDataRepository(self._on_demand.settings) as repository:
            latest_price = repository.latest_ohlcv_date()
            if latest_price is None:
                raise ValueError("DB에 일봉 자료가 없습니다.")
            selected = pd.Timestamp(as_of_date).date() if as_of_date is not None else latest_price
            if selected > latest_price:
                raise DatabaseDateMismatchError(
                    f"선택일 {selected}은 DB 마지막 일봉 {latest_price}보다 늦습니다."
                )
            flow = repository.get_market_investor_flow(selected)
            if flow.empty:
                raise ValueError(
                    f"{selected} 수급 자료가 DB에 없습니다. 수급 갱신을 먼저 실행하십시오."
                )
            master = repository.get_security_master_frame()
            prices = repository.get_market_ohlcv(selected, selected)
        if prices.empty:
            raise DatabaseDateMismatchError(f"{selected} 일봉이 DB에 없습니다.")
        rows = build_investor_flow_rows(flow, master, prices, screen_type)
        market, investor, direction = INVESTOR_FLOW_SCREEN_DEFINITIONS[screen_type]
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type] + (" (LS 원본 금액 검증)" if str(flow.attrs.get('source', '')).startswith('LS:T1702') else ""),
            run={
                "run_id": f"investor:{screen_type}:{selected}",
                "as_of_date": selected.isoformat(),
                "source": "LS_T1702_VERIFIED" if str(flow.attrs.get('source', '')).startswith('LS:T1702') else "POSTGRESQL_INVESTOR_FACTS",
                "data_source_mode": DATABASE_SOURCE_MODE,
                "market": market,
                "investor": investor,
                "direction": direction,
                "matched_count": len(rows),
            },
            rows=rows,
            latest_price_date=latest_price,
            latest_indicator_date=selected,
        )

    def _load_index_gainer_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
    ) -> ScreenDataset:
        snapshot, screen_date, latest_price_date = self._database_snapshot(as_of_date)
        membership = self._membership_for_screen(
            screen_type,
            screen_date,
            snapshot,
        )
        eligible_snapshot = exclude_spac_securities(snapshot)
        rows = (
            build_index_weekly_gainer_rows(eligible_snapshot, membership)
            if screen_type in INDEX_WEEKLY_SCREEN_TYPES
            else build_index_gainer_rows(
                eligible_snapshot,
                membership,
                limit=50 if screen_type == "kospi200_kosdaq150_daily_gainers" else 30,
            )
        )
        if rows.empty:
            raise ValueError(
                f"{membership.index_name} 구성종목과 {screen_date.isoformat()} "
                "기술지표 자료의 교집합이 없습니다."
            )

        generated_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
        run = {
            "run_id": f"database:{screen_type}:{screen_date.isoformat()}",
            "as_of_date": screen_date.isoformat(),
            "generated_at": generated_at,
            "source": "DATABASE",
            "data_source_mode": DATABASE_SOURCE_MODE,
            "membership_source": membership.source,
            "index_code": membership.index_code,
            "index_name": membership.index_name,
            "constituent_as_of_date": membership.as_of_date.isoformat(),
            "market": self._index_market(screen_type),
            "constituent_count": len(membership.tickers),
            "matched_count": int(
                eligible_snapshot["ticker"].astype(str).isin(membership.tickers).sum()
            ),
            "positive_count": self._positive_count(rows, screen_type),
        }
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=latest_price_date,
            latest_indicator_date=screen_date,
        )

    def _realtime_base(
        self,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> tuple[RealtimeQuoteSnapshot, DataFrame, dt.date]:
        quote_venue = str(quote_venue).strip().upper()
        if quote_venue not in QUOTE_VENUES:
            raise ValueError(f"Unsupported quote venue: {quote_venue!r}")
        cache_key = (
            f"{quote_venue}:latest"
            if as_of_date is None
            else f"{quote_venue}:{pd.Timestamp(as_of_date).date().isoformat()}"
        )
        now = time.monotonic()
        with self._realtime_cache_lock:
            cached = self._realtime_cache
            if (
                cached is not None
                and cached[0] == cache_key
                and now - cached[1] <= self.realtime_cache_seconds
            ):
                return cached[2], cached[3].copy(), cached[4]

            # Live quotes may already be on today's KST date while the DB
            # necessarily ends at the previous completed trading day.  Load
            # the latest complete DB snapshot as the indicator/reference
            # basis, then overlay the requested live quote date.
            database_snapshot, indicator_date, _ = (
                self._database_snapshot(None)
                if quote_venue == QUOTE_VENUE_KRX
                else self._database_snapshot(None, quote_venue)
            )

            universe_columns = ["ticker", "name", "market", "trade_date"]
            quotes = self.realtime_quote_fetcher(
                as_of_date,
                universe=database_snapshot[universe_columns].copy(),
                venue=quote_venue,
            )
            if quotes.as_of_date < indicator_date:
                database_snapshot, indicator_date, _ = (
                    self._database_snapshot(quotes.as_of_date)
                    if quote_venue == QUOTE_VENUE_KRX
                    else self._database_snapshot(quotes.as_of_date, quote_venue)
                )
            combined = overlay_realtime_quotes(database_snapshot, quotes)
            self._realtime_cache = (
                cache_key,
                time.monotonic(),
                quotes,
                combined.copy(),
                indicator_date,
            )
            return quotes, combined, indicator_date

    def _load_realtime_screen(
        self,
        screen_type: str,
        *,
        as_of_date: object | None,
        quote_venue: str = QUOTE_VENUE_KRX,
    ) -> ScreenDataset:
        quotes, snapshot, indicator_date = self._realtime_base(
            as_of_date,
            quote_venue,
        )
        membership: IndexMembership | None = None
        if screen_type in MARKET_RESULT_SCREEN_TYPES:
            rows = build_market_result_rows(snapshot, screen_type)
            market = MARKET_RESULT_DEFINITIONS[screen_type]
            markets = _market_values(screen_type)
            constituent_count = int(
                exclude_spac_securities(snapshot)["market"]
                .astype("string")
                .str.upper()
                .str.strip()
                .isin(markets)
                .sum()
            )
            matched_count = constituent_count
        elif screen_type in INDEX_RELATED_SCREEN_TYPES:
            membership = self._membership_for_screen(
                screen_type,
                quotes.as_of_date,
                snapshot,
            )
            rows = (
                build_index_weekly_gainer_rows(snapshot, membership)
                if screen_type in INDEX_WEEKLY_SCREEN_TYPES
                else build_index_gainer_rows(
                    snapshot,
                    membership,
                    limit=max(1, len(snapshot)),
                )
            )
            market = self._index_market(screen_type)
            constituent_count = len(membership.tickers)
            matched_count = int(
                snapshot["ticker"].astype(str).isin(membership.tickers).sum()
            )
        elif screen_type == "near_high_52w":
            rows = exclude_spac_securities(snapshot).copy()
            rows["high_52w"] = pd.to_numeric(rows["high_52w"], errors="coerce")
            rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
            rows = rows.loc[rows["high_52w"].gt(0) & rows["close"].gt(0)].copy()
            rows["distance_from_52w_high_pct"] = (
                rows["close"].div(rows["high_52w"]).sub(1).mul(100)
            ).round(6)
            rows = rows.sort_values(
                ["distance_from_52w_high_pct", "ticker"],
                ascending=[False, True], kind="mergesort",
            ).reset_index(drop=True)
            rows.insert(0, "screen_type", screen_type)
            rows.insert(0, "rank", np.arange(1, len(rows) + 1))
            market = "ALL"
            constituent_count = len(snapshot)
            matched_count = len(snapshot)
        else:
            result = build_market_screens(
                snapshot,
                as_of_date=quotes.as_of_date,
                comparison_ticker=None,
                top_n=50,
            )
            rows = result.frames()[screen_type]
            market = "ALL"
            constituent_count = result.universe_count
            matched_count = len(snapshot)

        run = {
            "run_id": f"realtime:{screen_type}:{quotes.as_of_date.isoformat()}",
            "as_of_date": quotes.as_of_date.isoformat(),
            "generated_at": quotes.retrieved_at.isoformat(timespec="seconds"),
            "retrieved_at": quotes.retrieved_at.isoformat(timespec="seconds"),
            "source": quotes.source,
            "data_source_mode": REALTIME_SOURCE_MODE,
            "quote_venue": quote_venue,
            "market": market,
            "constituent_count": constituent_count,
            "matched_count": matched_count,
            "quote_count": len(quotes.rows),
            "indicator_basis_date": indicator_date.isoformat(),
            "adjusted_reference_count": int(
                snapshot["reference_price_adjustment_factor"].ne(1.0).sum()
            ),
            "positive_count": self._positive_count(rows, screen_type),
        }
        if membership is not None:
            run.update(
                {
                    "membership_source": membership.source,
                    "index_code": membership.index_code,
                    "index_name": membership.index_name,
                    "constituent_as_of_date": membership.as_of_date.isoformat(),
                }
            )
        return ScreenDataset(
            screen_type=screen_type,
            title=SCREEN_TITLES[screen_type],
            run=run,
            rows=rows,
            latest_price_date=quotes.as_of_date,
            latest_indicator_date=indicator_date,
        )

    def resolve_ticker(self, ticker_or_name: object) -> str:
        """Resolve a six-digit ticker or an exact security name from local metadata."""

        if self._on_demand is not None:
            return self._on_demand.resolve_ticker(ticker_or_name)

        query = str(ticker_or_name).strip()
        if not query:
            raise ValueError("종목명 또는 6자리 종목코드를 입력하세요.")
        if query.isdigit():
            return normalize_ticker(query)
        with open_research_store(self.database_target, read_only=True) as store:
            matches = store.find_securities_by_name(query)
        if not matches:
            raise ValueError(f"종목명 '{query}'을 종목 마스터에서 찾을 수 없습니다.")
        if len(matches) > 1:
            tickers = ", ".join(str(row["ticker"]) for row in matches)
            raise ValueError(f"종목명 '{query}'이 여러 종목과 일치합니다: {tickers}")
        return normalize_ticker(matches[0]["ticker"])

    def search_securities(self, query: object, *, limit: int = 20) -> list[dict[str, str]]:
        """Search PostgreSQL security master by code/name for the Qt stock finder."""
        text = str(query).strip()
        if not text:
            return []
        if self._on_demand is None:
            raise RuntimeError("종목 검색에는 PostgreSQL 원천자료가 필요합니다.")
        with BaseDataRepository(self._on_demand.settings) as repository:
            master = repository.get_security_master_frame()
        if master.empty:
            return []
        code_col = "stock_code" if "stock_code" in master.columns else "ticker"
        name_col = "stock_name" if "stock_name" in master.columns else "name"
        market_col = "market" if "market" in master.columns else None
        codes = master[code_col].astype(str).str.zfill(6)
        names = master[name_col].fillna("").astype(str)
        mask = codes.str.contains(text, case=False, regex=False) | names.str.contains(text, case=False, regex=False)
        matches = master.loc[mask].copy().head(max(1, int(limit)))
        rows: list[dict[str, str]] = []
        for _, row in matches.iterrows():
            rows.append({
                "ticker": str(row.get(code_col, "")).zfill(6),
                "name": str(row.get(name_col, "")),
                "market": str(row.get(market_col, "")) if market_col else "",
            })
        return rows

    def clear_realtime_cache(self) -> None:
        """Discard live rows so database-only charts never inherit them."""

        with self._realtime_cache_lock:
            self._realtime_cache = None

    def _cached_realtime_chart_bar(self, ticker: str) -> dict[str, object] | None:
        with self._realtime_cache_lock:
            cached = self._realtime_cache
            if cached is None:
                return None
            rows = cached[3]
            matched = rows.loc[rows["ticker"].astype(str).eq(ticker)]
            if matched.empty:
                return None
            return matched.iloc[-1].to_dict()

    def load_chart(
        self,
        ticker: object,
        *,
        timeframes: tuple[str, ...] = ("D", "W"),
        include_investor: bool = False,
        quote_venue: str = QUOTE_VENUE_KRX,
        cancel_event: threading.Event | None = None,
    ) -> ChartDataset:
        code = self.resolve_ticker(ticker)
        live_bar = self._cached_realtime_chart_bar(code) if quote_venue == QUOTE_VENUE_KRX else None
        if self._on_demand is not None:
            result = self._on_demand.load_chart(
                code,
                timeframes=timeframes,
                include_investor=include_investor,
                live_bar=live_bar,
                venue=quote_venue,
                cancel_event=cancel_event,
            )
            return ChartDataset(
                ticker=result.ticker,
                name=result.name,
                market=result.market,
                industry=result.industry,
                daily=result.bars.get("D", DataFrame()),
                weekly=result.bars.get("W", DataFrame()),
                monthly=result.bars.get("M", DataFrame()),
                quarterly=result.bars.get("Q", DataFrame()),
                yearly=result.bars.get("Y", DataFrame()),
                investor=result.investor,
                loaded_timeframes=frozenset(result.bars),
                investor_loaded=include_investor,
            )
        with open_research_store(self.database_target, read_only=True) as store:
            history = store.get_adjusted_ohlcv(code)
            security = store.get_security(code) or {}
        if history.empty:
            raise ValueError(f"{code}의 저장된 수정주가 일봉이 없습니다.")

        indicators = calculate_technical_indicators(history, ticker=code)
        daily = history[["open", "high", "low", "close", "volume"]].copy()
        daily = daily.join(indicators.daily.drop(columns=["close"]))
        daily["previous_volume"] = daily["volume"].shift(1)
        daily["volume_color"] = np.select(
            [
                daily["volume"] > daily["previous_volume"],
                daily["volume"] < daily["previous_volume"],
            ],
            ["#d62728", "#1f77b4"],
            default="#808080",
        )
        macd_fast, macd_slow, macd_signal = (
            DEFAULT_CHART_ANALYSIS_POLICY.macd_oscillator.periods
        )
        ema_fast = daily["close"].ewm(
            span=macd_fast, adjust=False, min_periods=macd_fast
        ).mean()
        ema_slow = daily["close"].ewm(
            span=macd_slow, adjust=False, min_periods=macd_slow
        ).mean()
        daily["macd"] = ema_fast - ema_slow
        daily["macd_signal"] = (
            daily["macd"]
            .ewm(
                span=macd_signal,
                adjust=False,
                min_periods=macd_signal,
            )
            .mean()
        )
        daily["macd_oscillator"] = daily["macd"] - daily["macd_signal"]

        bollinger_period = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
        bollinger = daily["close"].rolling(bollinger_period, min_periods=bollinger_period)
        daily["bb_mid_20"] = daily["close"].ewm(
            span=bollinger_period, adjust=False, min_periods=bollinger_period
        ).mean()
        bollinger_deviation = bollinger.std(ddof=0)
        deviations = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.deviations
        daily["bb_upper_20_2"] = daily["bb_mid_20"] + deviations * bollinger_deviation
        daily["bb_lower_20_2"] = daily["bb_mid_20"] - deviations * bollinger_deviation

        daily["rsi_14"] = exponential_rsi(daily["close"], RSI_PERIOD)
        daily["rsi_signal_9"] = (
            daily["rsi_14"]
            .ewm(span=RSI_SIGNAL_PERIOD, adjust=False, min_periods=RSI_SIGNAL_PERIOD)
            .mean()
        )

        lowest_low = (
            daily["low"]
            .rolling(
                STOCHASTIC_K_PERIOD,
                min_periods=STOCHASTIC_K_PERIOD,
            )
            .min()
        )
        highest_high = (
            daily["high"]
            .rolling(
                STOCHASTIC_K_PERIOD,
                min_periods=STOCHASTIC_K_PERIOD,
            )
            .max()
        )
        price_range = (highest_high - lowest_low).replace(0, np.nan)
        fast_k = (daily["close"] - lowest_low) / price_range * 100.0
        daily["stoch_slow_k"] = fast_k.ewm(
            span=STOCHASTIC_K_SMOOTHING, adjust=False,
            min_periods=STOCHASTIC_K_SMOOTHING,
        ).mean()
        daily["stoch_slow_d"] = (
            daily["stoch_slow_k"]
            .ewm(span=STOCHASTIC_D_PERIOD, adjust=False, min_periods=STOCHASTIC_D_PERIOD)
            .mean()
        )

        weekly = indicators.weekly.copy()
        for window in EMA_WINDOWS:
            weekly[f"ema_{window}"] = (
                weekly["close"]
                .ewm(
                    span=window,
                    adjust=False,
                    min_periods=window,
                )
                .mean()
            )

        return ChartDataset(
            ticker=code,
            name=str(security.get("name") or code),
            market=str(security.get("market") or ""),
            industry=str(security.get("industry") or ""),
            daily=daily,
            weekly=weekly,
            loaded_timeframes=frozenset({"D", "W"}),
            investor_loaded=True,
        )
