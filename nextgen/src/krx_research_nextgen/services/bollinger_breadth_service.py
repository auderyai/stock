from __future__ import annotations

from datetime import date

import pandas as pd

from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY
from krx_research_nextgen.models.screening import (
    BOLLINGER_UNIVERSE,
    ScreeningKind,
    ScreeningQuery,
    ScreeningResult,
)
from krx_research_nextgen.repositories.bollinger_breadth_repository import BollingerBreadthRepository
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository


FORMULA_VERSION = "close-ema20-2std-core350-v2"
BOLLINGER_PERIOD = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.period
BOLLINGER_DEVIATIONS = DEFAULT_CHART_ANALYSIS_POLICY.bollinger.deviations


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
        df["middle"] = grouped.transform(
            lambda values: values.ewm(
                span=BOLLINGER_PERIOD,
                adjust=False,
                min_periods=BOLLINGER_PERIOD,
            ).mean()
        )
        deviation = grouped.transform(
            lambda values: values.rolling(
                BOLLINGER_PERIOD, min_periods=BOLLINGER_PERIOD
            ).std(ddof=0)
        )
        df["upper"] = df["middle"] + BOLLINGER_DEVIATIONS * deviation
        df["lower"] = df["middle"] - BOLLINGER_DEVIATIONS * deviation
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

    def weekly(self, frame: pd.DataFrame, as_of: date) -> list[dict[str, object]]:
        if frame.empty:
            raise ValueError("주봉 볼린저밴드 계산 대상 원자료가 없습니다.")
        daily = frame.copy()
        daily["trade_date"] = pd.to_datetime(daily["trade_date"])
        daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
        daily = daily.loc[daily["trade_date"].dt.date <= as_of].dropna(subset=["close"])
        daily["week_end"] = daily["trade_date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
        weekly = (
            daily.sort_values(["stock_code", "trade_date"])
            .groupby(["stock_code", "week_end"], sort=True, observed=True)
            .agg(
                trade_date=("trade_date", "last"), close=("close", "last"),
                stock_name=("stock_name", "last"), market=("market", "last"),
                trading_value=("trading_value", "sum"),
            )
            .reset_index()
        )
        grouped = weekly.groupby("stock_code", sort=False, observed=True)["close"]
        weekly["middle"] = grouped.transform(
            lambda values: values.ewm(
                span=BOLLINGER_PERIOD,
                adjust=False,
                min_periods=BOLLINGER_PERIOD,
            ).mean()
        )
        deviation = grouped.transform(
            lambda values: values.rolling(
                BOLLINGER_PERIOD, min_periods=BOLLINGER_PERIOD
            ).std(ddof=0)
        )
        weekly["upper"] = weekly["middle"] + BOLLINGER_DEVIATIONS * deviation
        current = weekly.groupby("stock_code", sort=False, observed=True).tail(1)
        current = current.loc[
            current["trade_date"].dt.date.eq(as_of)
            & current["upper"].notna()
            & current["close"].gt(current["upper"])
        ].copy()
        current["distance_pct"] = (current["close"] / current["upper"] - 1.0) * 100.0
        current = current.sort_values(
            ["distance_pct", "trading_value", "stock_code"],
            ascending=[False, False, True],
        )
        return current.to_dict("records")

    @staticmethod
    def summarize(rows: list[dict[str, object]]) -> dict[str, int]:
        return {
            key: sum(
                str(row["direction"]).lower() == direction
                and (market is None or str(row["market"]).upper() == market)
                for row in rows
            )
            for key, market, direction in (
                ("upper", None, "upper"), ("lower", None, "lower"),
                ("kospi_upper", "KOSPI", "upper"), ("kospi_lower", "KOSPI", "lower"),
                ("kosdaq_upper", "KOSDAQ", "upper"), ("kosdaq_lower", "KOSDAQ", "lower"),
            )
        }


class BollingerBreadthService:
    def __init__(self, source: ScreeningRepository, store: BollingerBreadthRepository) -> None:
        self._source, self._store = source, store
        self._calculator = BollingerBreadthCalculator()

    def run(self, query: ScreeningQuery) -> list[ScreeningResult]:
        selected_date = date.fromisoformat(query.as_of_date or self._source.latest_trade_date())
        rows, _ = self._calculate(selected_date, query.market)
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
        """Persist the canonical core-index breadth snapshot used by daily history."""
        rows, universe_count = self._calculate(selected_date, BOLLINGER_UNIVERSE)
        self._store.save(
            selected_date, rows, universe_count, self._calculator.summarize(rows),
            FORMULA_VERSION,
        )
        return rows, universe_count

    def _calculate(
        self, selected_date: date, universe: str
    ) -> tuple[list[dict[str, object]], int]:
        return self._calculator.calculate(
            self._source.bollinger_input(selected_date.isoformat(), universe=universe),
            selected_date,
        )

    def run_weekly(self, query: ScreeningQuery) -> list[ScreeningResult]:
        selected_date = date.fromisoformat(query.as_of_date or self._source.latest_trade_date())
        rows = self._calculator.weekly(
            self._source.bollinger_input(
                selected_date.isoformat(), universe=query.market
            ),
            selected_date,
        )[:query.limit]
        return [
            ScreeningResult(
                stock_code=str(row["stock_code"]),
                stock_name=str(row["stock_name"]),
                market=str(row["market"]),
                trade_date=selected_date.isoformat(),
                close=float(row["close"]),
                change_pct=float(row["distance_pct"]),
                trading_value=float(row["trading_value"]),
                high_52w=float(row["upper"]),
                rank=index,
            )
            for index, row in enumerate(rows, 1)
        ]
