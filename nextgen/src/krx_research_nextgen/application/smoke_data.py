from __future__ import annotations

import numpy as np
import pandas as pd


def build_sample_ohlcv(rows: int = 260) -> pd.DataFrame:
    """Deterministic synthetic data used only for Stage-1 GUI verification."""
    if rows < 80:
        raise ValueError("rows must be >= 80")

    rng = np.random.default_rng(5900)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=rows)

    step = rng.normal(loc=0.15, scale=1.25, size=rows)
    close = 100 + np.cumsum(step)
    open_ = close + rng.normal(loc=0.0, scale=0.7, size=rows)
    high = np.maximum(open_, close) + rng.uniform(0.2, 1.8, size=rows)
    low = np.minimum(open_, close) - rng.uniform(0.2, 1.8, size=rows)
    volume = rng.integers(100_000, 3_000_000, size=rows)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )
