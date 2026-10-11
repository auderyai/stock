from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RankLimit:
    """Validated user-selected result count shared by ranked Qt screens."""

    value: int = 50
    minimum: int = 1
    maximum: int = 5000

    def validate(self) -> "RankLimit":
        if not self.minimum <= int(self.value) <= self.maximum:
            raise ValueError(f"순위는 {self.minimum} ~ {self.maximum} 사이로 입력하십시오.")
        return self
