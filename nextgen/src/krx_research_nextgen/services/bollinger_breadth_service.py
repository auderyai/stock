from __future__ import annotations

from datetime import date

import pandas as pd

from krx_research_nextgen.models.screening import ScreeningKind, ScreeningQuery, ScreeningResult
from krx_research_nextgen.repositories.bollinger_breadth_repository import BollingerBreadthRepository
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository


FORMULA_VERSION = "close-ema20-2std-v1"


class BollingerBreadthCalculator:
    """Detect newly crossed close-price EMA20 Bollinger bands."""

    def calculate(self, frame: pd.DataFrame, as_of: date) -> tuple[list[dict[str, object]], int]:
        if frame.empty:
            raise ValueError("볼린저밴드 계산 대상 원자료가 없습니다.")
        df = frame.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values(["stock_code", "trade_date"])
        grouped = df.groupby("stock_code", sort=False)["close"]
        df["middle"] = grouped.transform(lambda s: s.ewm(span=20, adjust=False, min_periods=20).mean())
        deviation = grouped.transform(lambda s: s.rolling(20, min_periods=20).std(ddof=0))
        df["upper"] = df["middle"] + 2.0 * deviation
        df["lower"] = df["middle"] - 2.0 * deviation
        for column in ("close", "upper", "lower"):
            df[f"previous_{column}"] = df.groupby("stock_code", sort=False)[column].shift(1)
        current = df[df["trade_date"].dt.date == as_of].copy()
        if current.empty:
            raise ValueError(f"선택한 기준일의 OHLCV가 없습니다: {as_of.isoformat()}")
        valid = current[["close", "upper", "lower", "previous_close", "previous_upper", "previous_lower"]].notna().all(axis=1)
        current = current[valid]
        if current.empty:
            raise ValueError("볼린저밴드 판정이 가능한 종목이 0개입니다.")
        upper = current[(current["previous_close"] <= current["previous_upper"]) & (current["close"] > current["upper"])].copy()
        lower = current[(current["previous_close"] >= current["previous_lower"]) & (current["close"] < current["lower"])].copy()
        rows: list[dict[str, object]] = []
        for direction, selected, band in (("UPPER", upper, "upper"), ("LOWER", lower, "lower")):
            for item in selected.itertuples(index=False):
                band_value = float(getattr(item, band))
                rows.append({
                    "direction": direction, "stock_code": str(item.stock_code),
                    "stock_name": str(item.stock_name), "market": str(item.market),
                    "close": float(item.close), "trading_value": float(item.trading_value),
                    "band": band_value, "distance_pct": (float(item.close) / band_value - 1.0) * 100.0,
                    "formula_version": FORMULA_VERSION,
                })
        return rows, len(current)


class BollingerBreadthService:
    def __init__(self, source: ScreeningRepository, store: BollingerBreadthRepository) -> None:
        self._source, self._store = source, store
        self._calculator = BollingerBreadthCalculator()

    def run(self, query: ScreeningQuery) -> list[ScreeningResult]:
        selected_date = date.fromisoformat(query.as_of_date or self._source.latest_trade_date())
        rows, _ = self.refresh(selected_date)
        direction = "UPPER" if query.kind is ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT else "LOWER"
        selected = [row for row in rows if row["direction"] == direction]
        selected.sort(key=lambda row: (-abs(float(row["distance_pct"])), str(row["stock_code"])))
        results = [ScreeningResult(
            stock_code=str(row["stock_code"]), stock_name=str(row["stock_name"]),
            market=str(row["market"]), trade_date=selected_date.isoformat(), close=float(row["close"]),
            trading_value=float(row["trading_value"]), rank=index,
        ) for index, row in enumerate(selected, 1)]
        return self._source.enrich_display_fields(results)

    def refresh(self, selected_date: date) -> tuple[list[dict[str, object]], int]:
        rows, universe_count = self._calculator.calculate(
            self._source.bollinger_input(selected_date.isoformat()), selected_date
        )
        self._store.save(selected_date, rows, universe_count)
        return rows, universe_count
