from __future__ import annotations

from dataclasses import dataclass
import datetime as dt

from krx_research.policies.workstation_options import DATABASE_SOURCE_MODE


@dataclass(frozen=True, slots=True)
class ScreenQuery:
    """Immutable user request passed from Qt view to screening service."""

    screen_key: str
    start_date: dt.date
    end_date: dt.date
    source_mode: str = DATABASE_SOURCE_MODE
    quote_venue: str = "KRX"
    near_52w_low: float = -10.0
    near_52w_high: float = 0.0
    comparison_ticker: str | None = None
    top_n: int = 50

    def validate(self) -> None:
        if not self.screen_key.strip():
            raise ValueError("스크리닝 항목이 비어 있습니다.")
        if self.start_date > self.end_date:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        if self.near_52w_low > self.near_52w_high:
            raise ValueError("52주 범위 시작값은 종료값보다 클 수 없습니다.")
        if int(self.top_n) < 1 or int(self.top_n) > 5000:
            raise ValueError("순위는 1 ~ 5000 사이로 입력하십시오.")
        if self.screen_key == "ema_similarity" and not self.comparison_ticker:
            raise ValueError("이동평균 유사배열을 실행하려면 먼저 기준 종목을 검색해 선택하십시오.")
