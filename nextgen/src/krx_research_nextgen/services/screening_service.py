from __future__ import annotations

from dataclasses import replace

from krx_research_nextgen.infrastructure.task_logging import TaskLog
from krx_research_nextgen.models.screening import DateRange, RepeatedScreenResult, ScreeningKind, ScreeningQuery, ScreeningResult
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository


WEEKLY_KINDS = {ScreeningKind.WEEKLY_GAINERS, ScreeningKind.WEEKLY_TURNOVER_TOP, ScreeningKind.BOLLINGER_BREAKOUT}


class ScreeningService:
    def __init__(self, repository: ScreeningRepository) -> None:
        self._repository = repository

    def run(self, query: ScreeningQuery, *, period: DateRange | None = None) -> list[ScreeningResult]:
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
            if period is not None and not ranged:
                self.validate_period(period)
            latest = self._repository.latest_trade_date()
            task.info(f"latest_trade_date={latest}")
            if ranged:
                daily_rows = self._rows_by_date(query, self._period_dates(query, period))
                rows = [row for _, daily in daily_rows for row in daily]
            else:
                rows = self._repository.run(query)
            for key, value in dict(self._repository.last_metrics).items():
                task.info(f"{key}={value}")
            task.info(f"result_count={len(rows)}")
            if rows:
                task.info(f"first_result={rows[0].stock_code}|{rows[0].stock_name}")
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
        stored = set(self._repository.period_trade_dates(
            period.start.isoformat(), period.end.isoformat()
        ))
        missing = [value.isoformat() for value in (period.start, period.end)
                   if value.isoformat() not in stored]
        if missing:
            raise ValueError(
                "시작일과 종료일은 PostgreSQL에 저장된 거래일이어야 합니다. "
                f"DB에 없는 날짜: {', '.join(missing)}"
            )

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
        self.validate_period(period)
        dates = self._repository.period_dates_with_membership(
            query.market,
            self._repository.period_trade_dates(
                period.start.isoformat(), period.end.isoformat(),
                weekly=query.kind in WEEKLY_KINDS,
            ),
        )
        if not dates:
            raise ValueError("선택한 기간에 필요한 PostgreSQL 거래일 또는 지수 구성종목 자료가 없습니다.")
        return sorted(dates)

    def _rows_by_date(
        self, query: ScreeningQuery, dates: list[str]
    ) -> list[tuple[str, list[ScreeningResult]]]:
        return [(day, self._repository.run(replace(query, as_of_date=day))) for day in dates]

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
