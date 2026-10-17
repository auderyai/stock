from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd


@dataclass(frozen=True, slots=True)
class Security:
    code: str
    name: str


class PatternRepository(Protocol):
    def resolve(self, security: str) -> Security: ...
    def search_securities(self, query: str, limit: int = 20) -> list[dict[str, str]]: ...
    def history(self, start: date, end: date) -> pd.DataFrame: ...
    def latest_date(self) -> date: ...
    def latest(self, codes: list[str]) -> dict[str, dict]: ...
    def market_context(self, end: date, limit: int = 320) -> pd.DataFrame: ...
