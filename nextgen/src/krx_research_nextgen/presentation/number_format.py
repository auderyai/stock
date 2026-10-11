from __future__ import annotations

import math


def format_number(value, decimals: int = 0, *, missing: str = "") -> str:
    """Format numbers without a positive sign; only negative values show '-'."""
    if value is None: return missing
    number = float(value)
    if not math.isfinite(number): return missing
    if round(number, decimals) == 0: number = 0.0
    return f"{number:,.{decimals}f}"
