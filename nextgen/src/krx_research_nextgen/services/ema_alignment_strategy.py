from __future__ import annotations

from datetime import date

import pandas as pd

from krx_research.analytics.technical_indicators import exponential_moving_average
from krx_research_nextgen.models.screening import ScreeningResult


class EmaAlignmentStrategy:
    """Select complete-period bearish EMA alignment followed by a latest close breakout."""

    REQUIRED = {"stock_code", "stock_name", "market", "trade_date", "close"}

    def select(
        self, frame: pd.DataFrame, *, start: date, end: date, latest: date, limit: int
    ) -> list[ScreeningResult]:
        missing = self.REQUIRED.difference(frame.columns)
        if missing:
            raise ValueError(f"EMA 스크리닝 입력 열 누락: {', '.join(sorted(missing))}")
        data = frame.copy()
        data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
        data["close"] = pd.to_numeric(data["close"], errors="coerce")
        data = data.dropna(subset=["close"]).sort_values(["stock_code", "trade_date"])
        for span in (5, 10, 15):
            data[f"ema{span}"] = data.groupby("stock_code")["close"].transform(
                lambda values, window=span: exponential_moving_average(values, window)
            )

        period = data[data["trade_date"].between(start, end)].copy()
        expected = period["trade_date"].nunique()
        if not expected:
            return []
        period["aligned"] = (period["ema15"] > period["ema10"]) & (period["ema10"] > period["ema5"])
        qualified = period.groupby("stock_code").agg(rows=("trade_date", "nunique"), aligned=("aligned", "all"))
        codes = qualified.index[(qualified["rows"] == expected) & qualified["aligned"]]

        current = data[(data["trade_date"] == latest) & data["stock_code"].isin(codes)].copy()
        current = current[current["close"] > current["ema15"]]
        current["score"] = (current["close"] / current["ema15"] - 1.0) * 100.0
        current = current.sort_values(["score", "stock_code"], ascending=[False, True]).head(limit)
        return [
            ScreeningResult(
                stock_code=str(row.stock_code).zfill(6), stock_name=str(row.stock_name),
                market=str(row.market), trade_date=str(row.trade_date), close=float(row.close), rank=rank,
            )
            for rank, row in enumerate(current.itertuples(index=False), 1)
        ]
