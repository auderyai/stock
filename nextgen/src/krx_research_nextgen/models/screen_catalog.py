from __future__ import annotations

from dataclasses import dataclass

from krx_research_nextgen.models.screening import (
    CORE_INDEX_UNIVERSE,
    ScreeningKind,
)


@dataclass(frozen=True)
class ScreenSpec:
    title: str
    kind: ScreeningKind | None
    market: str = "ALL"
    uses_rank_limit: bool = True
    database_only: bool = False


@dataclass(frozen=True, slots=True)
class ScreenUniversePolicy:
    """Resolve one consistent universe for every screening entry point."""

    core_market: str = CORE_INDEX_UNIVERSE

    def resolve(self, configured_market: str, core_indices_only: bool) -> str:
        return self.core_market if core_indices_only else configured_market


SCREEN_UNIVERSE_POLICY = ScreenUniversePolicy()


SCREENS = (
    ScreenSpec("이동평균 유사배열", ScreeningKind.EMA_SIMILARITY),
    ScreenSpec("당일 52주 신고가", ScreeningKind.HIGH_52W),
    ScreenSpec("주봉 볼린저 돌파", ScreeningKind.BOLLINGER_BREAKOUT),
    ScreenSpec("KOSPI 주간 상승률 Top", ScreeningKind.WEEKLY_GAINERS, "KOSPI"),
    ScreenSpec("KOSDAQ 주간 상승률 Top", ScreeningKind.WEEKLY_GAINERS, "KOSDAQ"),
    ScreenSpec("KOSPI+KOSDAQ 주간 상승률 Top", ScreeningKind.WEEKLY_GAINERS, "KOSPI+KOSDAQ"),
    ScreenSpec("KOSPI 200 당일 상승률 Top", ScreeningKind.DAILY_GAINERS, "KOSPI200"),
    ScreenSpec("KOSDAQ 150 당일 상승률 Top", ScreeningKind.DAILY_GAINERS, "KOSDAQ150"),
    ScreenSpec("KOSPI 200+KOSDAQ 150 당일 상승률 Top", ScreeningKind.DAILY_GAINERS, CORE_INDEX_UNIVERSE),
    ScreenSpec("KOSPI 200 주간 상승률 Top", ScreeningKind.WEEKLY_GAINERS, "KOSPI200"),
    ScreenSpec("KOSDAQ 150 주간 상승률 Top", ScreeningKind.WEEKLY_GAINERS, "KOSDAQ150"),
    ScreenSpec("KOSPI 200+KOSDAQ 150 주간 상승률 Top", ScreeningKind.WEEKLY_GAINERS, CORE_INDEX_UNIVERSE),
    ScreenSpec("KOSPI 전체 당일 상승률 Top", ScreeningKind.DAILY_GAINERS, "KOSPI"),
    ScreenSpec("KOSDAQ 전체 당일 상승률 Top", ScreeningKind.DAILY_GAINERS, "KOSDAQ"),
    ScreenSpec("KOSPI+KOSDAQ 당일 상승률 Top", ScreeningKind.DAILY_GAINERS, "KOSPI+KOSDAQ"),
    ScreenSpec("KOSPI+KOSDAQ 당일 거래대금 Top", ScreeningKind.TURNOVER_TOP, "KOSPI+KOSDAQ"),
    ScreenSpec("KOSPI 거래대금 주간 Top", ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSPI"),
    ScreenSpec("KOSDAQ 거래대금 주간 Top", ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSDAQ"),
    ScreenSpec("KOSPI+KOSDAQ 거래대금 주간 Top", ScreeningKind.WEEKLY_TURNOVER_TOP, "KOSPI+KOSDAQ"),
    ScreenSpec("20일선+주도섹터", ScreeningKind.EMA20_LEADING_SECTOR, "KOSPI+KOSDAQ"),
    ScreenSpec("당일 볼린저밴드 상단 돌파", ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT, "ALL", False, True),
    ScreenSpec("당일 볼린저밴드 하단 돌파", ScreeningKind.DAILY_BOLLINGER_LOWER_BREAKOUT, "ALL", False, True),
    ScreenSpec("기간 EMA15>EMA10>EMA5 + 최신 종가>EMA15", ScreeningKind.EMA_BEARISH_ALIGNMENT_BREAKOUT, "ALL", True, True),
)
