from __future__ import annotations

import pandas as pd

from krx_research.analytics.chart_frames import build_chart_frame
from krx_research.models.workstation import ChartDataset
from krx_research.analytics.classic_strategies import assess_classic_strategies
from krx_research.policies.workstation_options import TIMEFRAME_LABELS
from krx_research.analytics.chart_frames import select_chart_window


class MarketIndexService:
    """Qt-free application service for composite/sector index browsing."""

    def __init__(self, repository):
        self._repository = repository

    def list_entries(self) -> list[dict]:
        entries = [row for row in self._repository.list_entries() if int(row.get("bars") or 0) > 0]
        entries.sort(key=self._sort_key)
        return entries

    def list_overview(self) -> tuple[list[dict], pd.DataFrame]:
        entries = self.list_entries()
        snapshots = self._snapshot_values(self._repository.list_snapshots())
        rows = []
        for item in entries:
            code = str(item["index_code"])
            level, daily, weekly, value, previous = snapshots.get(code, ("—",) * 5)
            rows.append({
                "market": str(item.get("market") or ""),
                "index_code": code,
                "index_name": self._display_name(item),
                "level": level,
                "daily_return": daily,
                "weekly_return": weekly,
                "trading_value_eok": value,
                "previous_trading_value_eok": previous,
            })
        return entries, pd.DataFrame(rows)

    def load_dataset(self, item: dict) -> ChartDataset:
        bars = self._repository.fetch_bars(str(item["index_code"]))
        return self._build_dataset(item, bars)

    @staticmethod
    def assess_strategies(dataset: ChartDataset, days: int | None):
        try:
            daily, weekly = select_chart_window(dataset, days)
            return assess_classic_strategies(daily, weekly)
        except Exception:
            return ()

    @staticmethod
    def _sort_key(item: dict) -> tuple:
        code = str(item.get("index_code") or "")
        return (
            0 if code == "1001" else 1 if code == "2001" else 2 if item.get("market") == "KOSPI" else 3,
            str(item.get("index_name") or ""),
        )

    @staticmethod
    def _display_name(item: dict) -> str:
        code = str(item.get("index_code") or "")
        if code == "1001":
            return "KOSPI 종합"
        if code == "2001":
            return "KOSDAQ 종합"
        return f"{item.get('market') or ''} · {item.get('index_name') or code}"

    @staticmethod
    def _snapshot_values(rows: list[dict]) -> dict[str, tuple[str, str, str, str, str]]:
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(str(row["index_code"]), []).append(row)
        result: dict[str, tuple[str, str, str, str, str]] = {}
        for code, history in grouped.items():
            history.sort(key=lambda row: row["trade_date"], reverse=True)

            def rate(offset: int) -> str:
                if len(history) <= offset:
                    return "—"
                current, previous = history[0].get("close_price"), history[offset].get("close_price")
                if current is None or previous is None or float(previous) <= 0:
                    return "—"
                return f"{(float(current) / float(previous) - 1) * 100:+.2f}%"

            def level(offset: int) -> str:
                if len(history) <= offset or history[offset].get("close_price") is None:
                    return "—"
                return f"{float(history[offset]['close_price']):,.2f}"

            def amount(offset: int) -> str:
                if len(history) <= offset or history[offset].get("trading_value") is None:
                    return "—"
                return f"{float(history[offset]['trading_value']) / 100_000_000:,.1f}"

            result[code] = (level(0), rate(1), rate(5), amount(0), amount(1))
        return result

    @staticmethod
    def _build_dataset(item: dict, bars: pd.DataFrame) -> ChartDataset:
        code = str(item["index_code"])
        rows = bars.copy()
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            rows[column] = pd.to_numeric(rows[column], errors="coerce")
        rows = rows.dropna(subset=["date", "open", "high", "low", "close"])
        rows = rows.loc[rows[["open", "high", "low", "close"]].gt(0).all(axis=1)]
        rows = rows.sort_values("date").drop_duplicates("date", keep="last")
        if rows.empty:
            raise ValueError(f"{code}의 표시 가능한 지수 일봉이 없습니다.")
        raw = pd.DataFrame({
            "stock_code": code,
            "trade_date": rows.date,
            "open_price": rows.open,
            "high_price": rows.high,
            "low_price": rows.low,
            "close_price": rows.close,
            "volume": rows.volume.fillna(0),
            "amount": 0,
        })
        frames = {period: build_chart_frame(raw, period) for period in TIMEFRAME_LABELS}
        name = "KOSPI 종합" if code == "1001" else "KOSDAQ 종합" if code == "2001" else str(item.get("index_name") or code)
        return ChartDataset(
            ticker=code,
            name=name,
            market=str(item.get("market") or ""),
            industry="",
            daily=frames["D"], weekly=frames["W"], monthly=frames["M"], quarterly=frames["Q"], yearly=frames["Y"],
            loaded_timeframes=frozenset(frames), investor_loaded=True,
        )
