from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WriteCandidate:
    stock_code: str
    trade_date: dt.date
    reason: str


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    return_code: int
    affected_rows: int = 0


@dataclass(frozen=True, slots=True)
class VerificationResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Menu2Snapshot:
    as_of: dt.date
    sector_master: int
    security_master: int
    kospi200: int
    kosdaq150: int
    sector_daily: int
    duplicate_sector_master: int
    duplicate_security_master: int
    duplicate_membership: int
    duplicate_sector_daily: int

    @property
    def duplicates(self) -> int:
        return (
            self.duplicate_sector_master
            + self.duplicate_security_master
            + self.duplicate_membership
            + self.duplicate_sector_daily
        )
