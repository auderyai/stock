from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from .models import UpdateResult
from .providers import MARKETS, BaseDataSourceError


class BaseProvider(Protocol):
    def fetch_ohlcv(self, target_date: date, market: str) -> pd.DataFrame: ...

    def fetch_investor_flow(self, target_date: date, market: str) -> pd.DataFrame: ...


class WriteRepository(Protocol):
    def start_update_run(self, target_date: date, mode: str = "incremental") -> int: ...

    def finish_update_run(
        self,
        run_id: int,
        *,
        status: str,
        ohlcv_rows: int = 0,
        investor_rows: int = 0,
        message: str | None = None,
    ) -> None: ...

    def get_update_state(self, dataset: str, market: str) -> date | None: ...

    def set_update_state(self, dataset: str, market: str, completed_date: date, details: dict | None = None) -> None: ...

    def is_date_complete(self, dataset: str, market: str, trade_date: date) -> bool: ...

    def set_date_coverage(
        self,
        dataset: str,
        market: str,
        trade_date: date,
        *,
        status: str,
        row_count: int,
        details: dict | None = None,
    ) -> None: ...

    def upsert_ohlcv(self, frame: pd.DataFrame) -> int: ...

    def upsert_investor_flow(self, frame: pd.DataFrame) -> int: ...


class IncrementalBaseUpdater:
    """Update only raw daily facts. It deliberately has no indicator/screen step."""

    def __init__(self, repository: WriteRepository, provider: BaseProvider) -> None:
        self.repository = repository
        self.provider = provider

    def update_date(
        self,
        target_date: date,
        *,
        markets: Sequence[str] = MARKETS,
        include_prices: bool = True,
        include_investor: bool = True,
        force: bool = False,
    ) -> UpdateResult:
        invalid = set(markets).difference(MARKETS)
        if invalid:
            raise ValueError(f"지원하지 않는 시장: {sorted(invalid)}")
        if target_date.weekday() >= 5:
            return UpdateResult(target_date, skipped=True, messages=("주말이므로 수집하지 않았습니다.",))

        run_id = self.repository.start_update_run(target_date)
        ohlcv_rows = 0
        investor_rows = 0
        completed: list[str] = []
        messages: list[str] = []
        source_errors: list[str] = []
        retry_required = False
        today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
        try:
            for market in markets:
                market_complete = True
                price_done = self.repository.is_date_complete("ohlcv_daily", market, target_date)
                if include_prices and (force or not price_done):
                    try:
                        prices = self.provider.fetch_ohlcv(target_date, market)
                    except BaseDataSourceError as exc:
                        message = str(exc)
                        messages.append(message)
                        source_errors.append(message)
                        market_complete = False
                    else:
                        if prices.empty:
                            messages.append(f"{market} {target_date}: 가격 자료 없음(휴장일 가능)")
                            if target_date < today_kst:
                                self.repository.set_date_coverage(
                                    "ohlcv_daily", market, target_date, status="no_data", row_count=0
                                )
                                self.repository.set_update_state(
                                    "ohlcv_daily", market, target_date, {"rows": 0, "no_data": True}
                                )
                            else:
                                retry_required = True
                                market_complete = False
                        else:
                            count = self.repository.upsert_ohlcv(prices)
                            ohlcv_rows += count
                            self.repository.set_date_coverage(
                                "ohlcv_daily", market, target_date, status="complete", row_count=count
                            )
                            self.repository.set_update_state(
                                "ohlcv_daily", market, target_date, {"rows": count}
                            )

                if include_investor:
                    flow_done = self.repository.is_date_complete("investor_flow_daily", market, target_date)
                    if force or not flow_done:
                        try:
                            flow = self.provider.fetch_investor_flow(target_date, market)
                        except BaseDataSourceError as exc:
                            message = str(exc)
                            messages.append(message)
                            source_errors.append(message)
                            market_complete = False
                        else:
                            if flow.empty:
                                messages.append(
                                    f"{market} {target_date}: 수급 자료 없음(휴장일 가능)"
                                )
                                # Historical empty days can be finalized as holidays;
                                # today's response must remain retryable.
                                if target_date < today_kst:
                                    self.repository.set_date_coverage(
                                        "investor_flow_daily",
                                        market,
                                        target_date,
                                        status="no_data",
                                        row_count=0,
                                    )
                                    self.repository.set_update_state(
                                        "investor_flow_daily",
                                        market,
                                        target_date,
                                        {"rows": 0, "no_data": True},
                                    )
                                else:
                                    retry_required = True
                                    market_complete = False
                            else:
                                count = self.repository.upsert_investor_flow(flow)
                                investor_rows += count
                                self.repository.set_date_coverage(
                                    "investor_flow_daily",
                                    market,
                                    target_date,
                                    status="complete",
                                    row_count=count,
                                )
                                self.repository.set_update_state(
                                    "investor_flow_daily", market, target_date, {"rows": count}
                                )
                if market_complete:
                    completed.append(market)
            status = "partial" if source_errors or retry_required else "completed"
            skipped = status == "completed" and ohlcv_rows == 0 and investor_rows == 0
            if skipped and not messages:
                messages.append(
                    f"{target_date}: 이미 완료된 데이터이므로 PostgreSQL 상태만 검증했습니다."
                )
            message = "; ".join(messages) if messages else "기본 데이터 증분 갱신 완료"
            self.repository.finish_update_run(
                run_id,
                status=status,
                ohlcv_rows=ohlcv_rows,
                investor_rows=investor_rows,
                message=message,
            )
            return UpdateResult(
                target_date,
                ohlcv_rows,
                investor_rows,
                tuple(completed),
                skipped,
                tuple(messages),
                {
                    "run_id": run_id,
                    "status": status,
                    "source_error_count": len(source_errors),
                    "retry_required": retry_required,
                },
            )
        except Exception as exc:
            self.repository.finish_update_run(
                run_id,
                status="failed",
                ohlcv_rows=ohlcv_rows,
                investor_rows=investor_rows,
                message=f"{type(exc).__name__}: {exc}",
            )
            raise
