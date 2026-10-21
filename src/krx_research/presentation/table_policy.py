from __future__ import annotations

from dataclasses import dataclass
from numbers import Number
import re
from typing import Iterable

import pandas as pd


@dataclass(frozen=True, slots=True)
class TablePresentationPolicy:
    """Toolkit-independent presentation policy shared by every Qt result table.

    Internal/database columns stay available to services and repositories, while
    views receive only user-facing columns and consistent formatting/alignment.
    """

    hidden_columns: tuple[str, ...] = ("score",)
    source_columns: tuple[str, ...] = (
        "source", "source_file", "source_url", "trading_value_source",
        "amount_source", "ticker_source", "market_source",
    )
    raw_trading_value_columns: tuple[str, ...] = (
        "trading_value", "amount", "weekly_trading_value",
    )
    ticker_columns: tuple[str, ...] = ("ticker", "stock_code", "code", "index_code", "symbol")
    stock_ticker_columns: tuple[str, ...] = ("ticker", "stock_code", "code")
    code_width: int = 6
    rank_columns: tuple[str, ...] = ("rank", "position")
    volume_columns: tuple[str, ...] = ("volume",)
    investor_net_columns: tuple[str, ...] = ("investor_net_value",)
    market_cap_columns: tuple[str, ...] = ("market_cap",)
    cash_value_columns: tuple[str, ...] = ("buy_value", "sell_value")
    center_columns: tuple[str, ...] = ("flow_direction",)
    right_columns: tuple[str, ...] = ()
    date_reference_columns: tuple[str, ...] = ("screen_date", "as_of_date", "report_date")

    def prepare(self, frame: pd.DataFrame | None) -> pd.DataFrame:
        if frame is None:
            return pd.DataFrame()
        prepared = frame.copy()
        drop: list[str] = [column for column in self.hidden_columns if column in prepared.columns]

        # User requested source metadata never be exposed in result grids.
        drop.extend(column for column in self.source_columns if column in prepared.columns)

        # Keep the already-normalized 거래대금(억원) column and suppress raw won columns
        # only when an eok/estimated presentation column is present.
        has_eok = any(
            column in prepared.columns
            for column in (
                "estimated_trading_value", "estimated_trading_value_eok",
                "trading_value_eok", "latest_trading_value_eok",
                "source_trading_value_eok", "weekly_trading_value_eok",
            )
        )
        if has_eok:
            drop.extend(column for column in self.raw_trading_value_columns if column in prepared.columns)

        # 거래일 is redundant only when a 기준일 column is present and every non-null
        # 거래일 equals that 기준일. Date-range dashboards therefore retain trade_date.
        if "trade_date" in prepared.columns:
            reference = next((c for c in self.date_reference_columns if c in prepared.columns), None)
            if reference and self._same_dates(prepared["trade_date"], prepared[reference]):
                drop.append("trade_date")

        if drop:
            prepared = prepared.drop(columns=list(dict.fromkeys(drop)), errors="ignore")
        return prepared

    def default_sort(self, frame: pd.DataFrame) -> tuple[str, bool] | None:
        """Return the authoritative initial sort without guessing feature scores."""
        column = next((name for name in self.rank_columns if name in frame.columns), None)
        return (column, True) if column else None

    @staticmethod
    def _same_dates(left: pd.Series, right: pd.Series) -> bool:
        l = pd.to_datetime(left, errors="coerce").dt.date
        r = pd.to_datetime(right, errors="coerce").dt.date
        mask = l.notna() | r.notna()
        if not mask.any():
            return True
        return bool((l[mask] == r[mask]).all())

    _NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$")

    def alignment(self, column: str, value) -> str:
        """Global table rule: numeric right, text left, identity/code centered.

        Explicit semantic center/right columns remain available for the few fields
        the user asked to keep special (for example 판정/구분).
        """
        if column in self.ticker_columns:
            return "center"
        if column in self.center_columns:
            return "center"
        if (
            column in self.right_columns
            or column in self.rank_columns
            or column in self.volume_columns
            or column in self.investor_net_columns
            or column in self.market_cap_columns
            or column in self.cash_value_columns
            or self._is_numeric_like(value)
        ):
            return "right"
        return "left"

    def header_alignment(self, column: str, series: pd.Series | None = None) -> str:
        """Center every table header across all Qt programs."""
        return "center"

    @staticmethod
    def sort_key(series: pd.Series) -> pd.Series:
        """Return a stable numeric key for numeric values and formatted numeric text."""
        text = series.astype("string").str.strip()
        meaningful = series.notna() & text.ne("")
        normalized = text.str.replace(",", "", regex=False).str.removesuffix("%")
        numeric = pd.to_numeric(normalized, errors="coerce")
        if meaningful.any() and numeric[meaningful].notna().all():
            return numeric
        return text.str.casefold()

    @classmethod
    def _is_numeric_like(cls, value) -> bool:
        if isinstance(value, bool) or value is None:
            return False
        if isinstance(value, Number):
            return True
        try:
            if pd.isna(value):
                return False
        except Exception:
            pass
        text = str(value).strip()
        return bool(text and cls._NUMERIC_TEXT.fullmatch(text))

    @classmethod
    def _series_is_numeric(cls, series: pd.Series | None) -> bool:
        if series is None or series.empty:
            return False
        if pd.api.types.is_numeric_dtype(series.dtype):
            return True
        values = [value for value in series.tolist() if not pd.isna(value)]
        return bool(values) and all(cls._is_numeric_like(value) for value in values)

    def format_value(self, column: str, value) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            return ", ".join(map(str, value))
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        if column in self.ticker_columns:
            text = str(value).strip().removesuffix(".0")
            return (
                text.zfill(self.code_width)
                if column in self.stock_ticker_columns and self.code_width and text.isdigit()
                else text
            )
        if column in self.rank_columns or column == "appearance_count":
            try:
                return f"{int(float(value)):,}"
            except Exception:
                return str(value)
        if column in self.volume_columns:
            try:
                return f"{int(round(float(value))):,}"
            except Exception:
                return str(value)
        if column in self.investor_net_columns:
            try:
                return f"{float(value) / 100_000_000.0:,.1f}"
            except Exception:
                return str(value)
        if column in self.market_cap_columns or column in self.cash_value_columns:
            try:
                return f"{float(value) / 100_000_000.0:,.1f}"
            except Exception:
                return str(value)
        if column in {
            "close", "open", "high", "low", "high_52w",
            "close_price", "open_price", "high_price", "low_price",
        }:
            try:
                return f"{float(value):,.0f}"
            except Exception:
                return str(value)
        if column in {
            "estimated_trading_value", "estimated_trading_value_eok",
            "trading_value_eok", "latest_trading_value_eok",
            "source_trading_value_eok", "weekly_trading_value_eok",
        }:
            try:
                return f"{float(value):,.1f}"
            except Exception:
                return str(value)
        if isinstance(value, float):
            return f"{value:,.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)


DEFAULT_TABLE_POLICY = TablePresentationPolicy()
