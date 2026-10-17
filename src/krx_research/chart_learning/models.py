from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ChartPatternSample:
    image: Path
    ticker: str
    company_name: str
    start: date
    end: date
    assessment: str
    rationale: str


@dataclass(frozen=True, slots=True)
class StoredChartPattern:
    sample_id: str
    ticker: str
    company_name: str
    db_reference_date: date
    canonical_path: Path
    duplicate: bool
    features: dict
