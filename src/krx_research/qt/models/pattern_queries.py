from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum, StrEnum


class MovingAverageKind(StrEnum):
    SMA = "SMA"
    EMA = "EMA"
    WMA = "WMA"


@dataclass(frozen=True, slots=True)
class MovingAverageSpec:
    kind: MovingAverageKind = MovingAverageKind.SMA
    periods: tuple[int, ...] = (5, 20, 60)

    def __post_init__(self) -> None:
        periods = tuple(sorted(set(map(int, self.periods))))
        if not periods or len(periods) > 8 or periods[0] < 2 or periods[-1] > 500:
            raise ValueError("이동평균 기간은 2~500일에서 최대 8개까지 지정할 수 있습니다.")
        object.__setattr__(self, "kind", MovingAverageKind(str(self.kind).upper()))
        object.__setattr__(self, "periods", periods)


@dataclass(frozen=True, slots=True)
class PatternSearchQuery:
    security: str
    start: date
    end: date
    averages: MovingAverageSpec = MovingAverageSpec()
    top_n: int = 20
    include_price: bool = True
    include_volume: bool = False

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("패턴 시작일은 종료일보다 늦을 수 없습니다.")
        if not str(self.security).strip():
            raise ValueError("기준 종목을 입력하십시오.")
        if not 1 <= int(self.top_n) <= 100:
            raise ValueError("검색 결과 수는 1~100이어야 합니다.")
        if not self.include_price and not self.averages.periods:
            raise ValueError("비교할 가격 또는 이동평균선이 필요합니다.")


@dataclass(frozen=True, slots=True)
class PeriodPatternQuery:
    security: str
    start: date
    end: date
    top_n: int = 20

    def __post_init__(self) -> None:
        if not str(self.security).strip():
            raise ValueError("기준 종목을 입력하십시오.")
        if self.start >= self.end:
            raise ValueError("패턴 시작일은 종료일보다 빨라야 합니다.")
        if not 1 <= self.top_n <= 100:
            raise ValueError("검색 결과 수는 1~100이어야 합니다.")


class CurrentPatternKind(str, Enum):
    DOUBLE_BOTTOM = "현재 이중바닥"
    CUP_WITH_HANDLE = "현재 컵위드핸들"


@dataclass(frozen=True, slots=True)
class CurrentPatternQuery:
    kind: CurrentPatternKind
    top_n: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.top_n <= 100:
            raise ValueError("검색 결과 수는 1~100이어야 합니다.")
