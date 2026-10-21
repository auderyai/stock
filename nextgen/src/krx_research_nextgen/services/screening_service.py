from __future__ import annotations

from dataclasses import replace
from datetime import date
from time import perf_counter

from krx_research_nextgen.infrastructure.task_logging import TaskLog
from krx_research_nextgen.models.screening import DateRange, RepeatedScreenResult, ScreeningKind, ScreeningQuery, ScreeningResult
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.bollinger_breadth_service import BollingerBreadthService
from krx_research_nextgen.services.ema_alignment_strategy import EmaAlignmentStrategy


WEEKLY_KINDS = {ScreeningKind.WEEKLY_GAINERS, ScreeningKind.WEEKLY_TURNOVER_TOP, ScreeningKind.BOLLINGER_BREAKOUT}

DATABASE_QUERIES = {
    ScreeningKind.EMA_SIMILARITY: "ema_similarity",
    ScreeningKind.HIGH_52W: "high_52w",
    ScreeningKind.NEAR_HIGH_52W: "near_high_52w",
    ScreeningKind.DAILY_GAINERS: "daily_gainers",
    ScreeningKind.WEEKLY_GAINERS: "weekly_gainers",
    ScreeningKind.TURNOVER_TOP: "turnover_top",
    ScreeningKind.WEEKLY_TURNOVER_TOP: "weekly_turnover_top",
    ScreeningKind.EMA20_LEADING_SECTOR: "ema20_leading_sector",
}


class ScreeningService:
    def __init__(self, repository: ScreeningRepository, realtime_repository=None,
                 bollinger_breadth: BollingerBreadthService | None = None,
                 ema_alignment: EmaAlignmentStrategy | None = None) -> None:
        self._repository = repository
        self._realtime = realtime_repository
        self._bollinger_breadth = bollinger_breadth
        self._ema_alignment = ema_alignment or EmaAlignmentStrategy()

    def run(self, query: ScreeningQuery, *, period: DateRange | None = None) -> list[ScreeningResult]:
        if query.source_mode == "realtime":
            if self._realtime is None:
                raise RuntimeError("실시간 조회 서비스가 구성되지 않았습니다.")
            return self._realtime.run(query)
        if query.source_mode != "database":
            raise ValueError(f"지원하지 않는 자료 종류입니다: {query.source_mode}")

        latest = self._repository.latest_trade_date()
        if period is not None:
            dates = self._calendar_trade_dates(
                period, latest, weekly=query.kind in WEEKLY_KINDS
            )
            query = replace(query, as_of_date=dates[-1])
        if query.kind in {
            ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT,
            ScreeningKind.DAILY_BOLLINGER_LOWER_BREAKOUT,
        }:
            if self._bollinger_breadth is None:
                raise RuntimeError("볼린저 시장 집계 서비스가 구성되지 않았습니다.")
            with TaskLog("bollinger_breadth_screening", kind=query.kind.value,
                         market=query.market, as_of_date=query.as_of_date) as task:
                rows = self._bollinger_breadth.run(query)
                task.info(f"result_count={len(rows)}")
                return rows
        with TaskLog(
            "screening",
            kind=query.kind.value,
            market=query.market,
            limit=query.limit,
            ohlcv_relation=self._repository.ohlcv_relation,
            master_relation=self._repository.master_relation,
        ) as task:
            ranged = (
                period is not None and query.kind is ScreeningKind.HIGH_52W
                and period.start != period.end
            )
            task.info(f"latest_trade_date={latest}")
            if ranged:
                daily_rows = self._rows_by_date(query, self._period_dates(query, period))
                rows = [row for _, daily in daily_rows for row in daily]
            else:
                rows = self._run_database(query, period, latest)
            for key, value in dict(self._repository.last_metrics).items():
                task.info(f"{key}={value}")
            task.info(f"result_count={len(rows)}")
            if rows:
                task.info(f"first_result={rows[0].stock_code}|{rows[0].stock_name}")
            return rows

    def _run_database(
        self, query: ScreeningQuery, period: DateRange | None, latest: str
    ) -> list[ScreeningResult]:
        if not 1 <= query.limit <= 500:
            raise ValueError("screening limit must be 1..500")
        self._repository.last_metrics = {}
        started = perf_counter()
        if query.kind is ScreeningKind.EMA_BEARISH_ALIGNMENT_BREAKOUT:
            if period is None:
                raise ValueError("EMA 기간 스크리닝에는 시작일과 종료일이 필요합니다.")
            frame = self._repository.ema_alignment_input(
                period.start.isoformat(), latest, query.market
            )
            rows = self._ema_alignment.select(
                frame, start=period.start, end=period.end,
                latest=date.fromisoformat(latest), limit=query.limit,
            )
        elif query.kind is ScreeningKind.BOLLINGER_BREAKOUT:
            if self._bollinger_breadth is None:
                raise RuntimeError("볼린저 계산 서비스가 구성되지 않았습니다.")
            rows = self._bollinger_breadth.run_weekly(query)
        else:
            method_name = DATABASE_QUERIES.get(query.kind)
            if method_name is None:
                raise ValueError(f"Unsupported screening kind: {query.kind}")
            query_method = getattr(self._repository, method_name, None)
            if not callable(query_method):
                raise TypeError(f"Repository does not implement {method_name}()")
            rows = query_method(query)
        enrich_started = perf_counter()
        rows = self._repository.enrich_display_fields(rows)
        self._repository.last_metrics.update(
            display_enrichment_seconds=perf_counter() - enrich_started,
            repository_total_seconds=perf_counter() - started,
            result_count=len(rows),
        )
        return rows

    def status(self) -> dict[str, object]:
        with TaskLog("screening_status") as task:
            earliest = self._repository.earliest_trade_date()
            latest = self._repository.latest_trade_date()
            result = {
                "ohlcv_relation": self._repository.ohlcv_relation,
                "master_relation": self._repository.master_relation,
                "earliest_trade_date": earliest,
                "latest_trade_date": latest,
                "trade_dates": self._repository.period_trade_dates(earliest, latest),
            }
            for key, value in result.items():
                task.info(f"{key}={len(value)}" if key == "trade_dates" else f"{key}={value}")
            return result

    def validate_period(self, period: DateRange) -> None:
        self._calendar_trade_dates(period, self._repository.latest_trade_date())

    def _calendar_trade_dates(
        self, period: DateRange, latest: str, *, weekly: bool = False
    ) -> list[str]:
        """Resolve calendar boundaries to stored sessions without inventing dates."""
        dates = self._repository.period_trade_dates(
            period.start.isoformat(), period.end.isoformat(), weekly=weekly
        )
        if not dates:
            raise ValueError("선택한 달력 구간 안에 PostgreSQL 거래일이 없습니다.")
        if period.end > date.fromisoformat(latest):
            raise ValueError(f"종료일은 최신 DB 거래일({latest}) 이후일 수 없습니다.")
        return sorted(dates)

    def run_repeated(self, query: ScreeningQuery, period: DateRange) -> list[RepeatedScreenResult]:
        """Aggregate stocks appearing in the selected screen on at least two stored periods."""
        start, end = period.start.isoformat(), period.end.isoformat()
        with TaskLog("repeated_screening", kind=query.kind.value, start=start, end=end, limit=query.limit) as task:
            dates = self._period_dates(query, period)
            if len(dates) < 2:
                raise ValueError("기간 내 다빈도 종목은 서로 다른 거래일이 2일 이상 필요합니다.")
            daily_rows = self._rows_by_date(query, dates)
            appearances: dict[str, dict[str, ScreeningResult]] = {}
            for trade_date, rows in daily_rows:
                for row in rows:
                    appearances.setdefault(row.stock_code, {})[trade_date] = row
            repeated = {code: rows for code, rows in appearances.items() if len(rows) >= 2}
            metrics = self._repository.period_stock_metrics(list(repeated), start, end)

            def numbers(code: str, days: list[str], key: str) -> list[float]:
                return [float(value) for day in days if (value := metrics.get((code, day), {}).get(key)) is not None]

            results = []
            for code, by_date in repeated.items():
                days = sorted(by_date); latest = by_date[days[-1]]; latest_metric = metrics.get((code, days[-1]), {})
                daily, weekly = numbers(code, days, "daily_pct"), numbers(code, days, "weekly_pct")
                results.append(RepeatedScreenResult(
                    len(days), code, str(latest_metric.get("stock_name") or latest.stock_name),
                    str(latest_metric.get("industry") or latest.industry), tuple(days),
                    sum(daily) / len(daily) if daily else None, max(daily) if daily else None,
                    sum(weekly) / len(weekly) if weekly else None, max(weekly) if weekly else None,
                    None if latest_metric.get("trading_value") is None else float(latest_metric["trading_value"]),
                    None if latest_metric.get("close") is None else float(latest_metric["close"]),
                ))
            results.sort(key=lambda row: (-row.appearance_count, row.stock_name, row.stock_code))
            task.info(f"periods={len(daily_rows)}")
            task.info(f"occurrences={sum(len(x) for x in appearances.values())}")
            task.info(f"repeated_stocks={len(results)}")
            return results

    def _period_dates(self, query: ScreeningQuery, period: DateRange) -> list[str]:
        dates = self._repository.period_dates_with_membership(
            query.market,
            self._calendar_trade_dates(
                period, self._repository.latest_trade_date(),
                weekly=query.kind in WEEKLY_KINDS,
            ),
        )
        if not dates:
            raise ValueError("선택한 기간에 필요한 PostgreSQL 거래일 또는 지수 구성종목 자료가 없습니다.")
        return sorted(dates)

    def _rows_by_date(
        self, query: ScreeningQuery, dates: list[str]
    ) -> list[tuple[str, list[ScreeningResult]]]:
        return [(day, self.run(replace(query, as_of_date=day))) for day in dates]

    def ensure_performance_indexes(self) -> list[dict[str, str]]:
        with TaskLog(
            "screening_index_check",
            relation=self._repository.ohlcv_relation,
        ) as task:
            results = self._repository.ensure_performance_indexes()
            for result in results:
                task.info(
                    "index="
                    + result.get("index", "")
                    + " status="
                    + result.get("status", "")
                    + " detail="
                    + result.get("detail", "")
                )
            return results
