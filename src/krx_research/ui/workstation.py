"""Compatibility exports for the PySide6 new_stock workstation.

All graphical widgets live in :mod:`krx_research.qt`.  This module intentionally
contains no legacy GUI imports.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.windows.workstation_window import WorkstationWindow
from krx_research.qt.workstation import launch_workstation
from .data import DAILY_GAINER_SCREEN_TYPES, ScreenDataset

WorkstationApp = WorkstationWindow


def build_chart_navigation_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame()
    frame = rows.copy().reset_index(drop=True)
    preferred = [c for c in ("ticker", "name", "stock_name", "market", "screen_date") if c in frame.columns]
    return frame.loc[:, preferred] if preferred else frame


def build_screen_export_frame(screen: ScreenDataset) -> pd.DataFrame:
    return screen.rows.copy().reset_index(drop=True)


def export_screen_to_xlsx(screen: ScreenDataset, path: str | Path) -> None:
    build_screen_export_frame(screen).to_excel(Path(path), index=False)


def build_repeated_screen_export_frame(rows: pd.DataFrame) -> pd.DataFrame:
    return rows.copy().reset_index(drop=True)


def export_repeated_screen_to_xlsx(rows: pd.DataFrame, path: str | Path) -> None:
    build_repeated_screen_export_frame(rows).to_excel(Path(path), index=False)


def build_repeated_screen_rows(rows: pd.DataFrame, *, minimum_count: int = 2) -> pd.DataFrame:
    if rows is None or rows.empty or "ticker" not in rows.columns:
        return pd.DataFrame()
    frame = rows.copy()
    group = frame.groupby("ticker", dropna=False)
    counts = group.size().rename("appearance_count")
    repeated = frame.merge(counts, left_on="ticker", right_index=True)
    repeated = repeated.loc[repeated["appearance_count"] >= int(minimum_count)].copy()
    sort_cols = [c for c in ("appearance_count", "ticker", "screen_date") if c in repeated.columns]
    if sort_cols:
        repeated = repeated.sort_values(sort_cols, ascending=[False] + [True] * (len(sort_cols) - 1))
    return repeated.reset_index(drop=True)


def rise_reason_date_for_screen(screen: ScreenDataset | None) -> dt.date | None:
    if screen is None or screen.screen_type not in DAILY_GAINER_SCREEN_TYPES:
        return None
    return pd.Timestamp(screen.run["as_of_date"]).date()


RepeatedScreenWindow = WorkstationWindow


__all__ = [
    "ChartWindow", "RepeatedScreenWindow", "WorkstationApp", "WorkstationWindow",
    "build_chart_navigation_rows", "build_repeated_screen_export_frame",
    "build_repeated_screen_rows", "build_screen_export_frame",
    "export_repeated_screen_to_xlsx", "export_screen_to_xlsx",
    "launch_workstation", "rise_reason_date_for_screen",
]
