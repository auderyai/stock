from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityRecord:
    stock_code: str
    stock_name: str
    market: str = ""
