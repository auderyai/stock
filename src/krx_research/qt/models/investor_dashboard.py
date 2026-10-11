from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd


INVESTORS = {"foreign": "외국인", "institution": "기관", "individual": "개인"}


@dataclass(slots=True)
class InvestorDashboardData:
    requested_start: dt.date
    requested_end: dt.date
    actual_days: tuple[dt.date, ...]
    market_days: tuple[dt.date, ...]
    market_totals: dict[tuple[str, str], int]
    market_counts: dict[str, int]
    rankings: dict[tuple[str, str, str], pd.DataFrame]
