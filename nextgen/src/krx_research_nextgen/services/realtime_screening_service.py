from __future__ import annotations

from krx_research_nextgen.models.screening import ScreeningKind, ScreeningQuery, ScreeningResult


SCREEN_KEYS = {
    (ScreeningKind.HIGH_52W, "ALL"): "high_52w",
    (ScreeningKind.NEAR_HIGH_52W, "ALL"): "near_high_52w",
    (ScreeningKind.BOLLINGER_BREAKOUT, "ALL"): "bollinger_breakout",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI"): "kospi_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSDAQ"): "kosdaq_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI+KOSDAQ"): "weekly_return",
    (ScreeningKind.DAILY_GAINERS, "KOSPI200"): "kospi200_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSDAQ150"): "kosdaq150_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSPI200+KOSDAQ150"): "kospi200_kosdaq150_daily_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI200"): "kospi200_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSDAQ150"): "kosdaq150_weekly_gainers",
    (ScreeningKind.WEEKLY_GAINERS, "KOSPI200+KOSDAQ150"): "kospi200_kosdaq150_weekly_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSPI"): "kospi_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSDAQ"): "kosdaq_daily_gainers",
    (ScreeningKind.DAILY_GAINERS, "KOSPI+KOSDAQ"): "kospi_kosdaq_daily_gainers",
    (ScreeningKind.TURNOVER_TOP, "KOSPI+KOSDAQ"): "kospi_kosdaq_daily_trading_value",
    (ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSPI"): "kospi_weekly_trading_value",
    (ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSDAQ"): "kosdaq_weekly_trading_value",
    (ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSPI+KOSDAQ"): "kospi_kosdaq_weekly_trading_value",
}


class RealtimeScreeningService:
    """Own live-screen selection rules; the repository only retrieves and maps data."""

    def __init__(self, repository) -> None:
        self._repository = repository

    def run(self, query: ScreeningQuery) -> list[ScreeningResult]:
        if query.kind is ScreeningKind.EMA_SIMILARITY:
            raise ValueError("이동평균 유사배열은 과거 구간 계산이 필요하므로 데이터베이스를 선택하십시오.")
        key = SCREEN_KEYS.get((query.kind, query.market)) or SCREEN_KEYS.get((query.kind, "ALL"))
        if key is None:
            raise ValueError(f"{query.kind.value}은 실시간 조회를 지원하지 않습니다. 데이터베이스를 선택하십시오.")
        rows = self._repository.load(key, query)
        if query.kind is ScreeningKind.NEAR_HIGH_52W:
            rows = [
                row for row in rows
                if row.distance_from_high_pct is not None
                and query.near_low <= row.distance_from_high_pct <= query.near_high
            ]
        if not rows:
            raise ValueError("실시간 시세는 수집되었지만 선택 조건에 맞는 종목이 0건입니다.")
        return rows[:query.limit]
