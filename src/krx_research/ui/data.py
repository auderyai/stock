"""Narrow compatibility API for callers of the former mixed UI/data module."""

from krx_research.analytics.screening import (
    build_index_gainer_rows,
    build_index_weekly_gainer_rows,
    build_market_gainer_rows,
    build_market_trading_value_rows,
    overlay_realtime_quotes,
)
from krx_research.data_engine.workstation_repository import WorkstationData
from krx_research.models.workstation import ChartDataset, ScreenDataset
from krx_research.policies.screen_catalog import (
    DAILY_GAINER_SCREEN_TYPES,
    INDEX_RELATED_SCREEN_TYPES,
    INDEX_WEEKLY_SCREEN_TYPES,
    MARKET_GAINER_DEFINITIONS,
    MARKET_GAINER_SCREEN_TYPES,
    MARKET_RESULT_SCREEN_TYPES,
    MARKET_TRADING_VALUE_SCREEN_TYPES,
    WEEKLY_SCREEN_TYPES,
)
from krx_research.policies.workstation_options import (
    DATABASE_SOURCE_MODE,
    DATA_SOURCE_MODES,
    REALTIME_SOURCE_MODE,
    SCREEN_TITLES,
)
from krx_research.analytics.chart_frames import (
    calculate_volume_profile, select_chart_window,
)
from krx_research.qt.services.screen_dataset_service import (
    describe_screen_freshness, filter_52w_distance,
)

__all__ = (
    "DAILY_GAINER_SCREEN_TYPES", "DATA_SOURCE_MODES", "DATABASE_SOURCE_MODE",
    "INDEX_RELATED_SCREEN_TYPES", "INDEX_WEEKLY_SCREEN_TYPES",
    "MARKET_GAINER_DEFINITIONS", "MARKET_GAINER_SCREEN_TYPES",
    "MARKET_RESULT_SCREEN_TYPES", "MARKET_TRADING_VALUE_SCREEN_TYPES",
    "REALTIME_SOURCE_MODE", "SCREEN_TITLES", "WEEKLY_SCREEN_TYPES",
    "ChartDataset", "ScreenDataset", "WorkstationData",
    "build_index_gainer_rows", "build_index_weekly_gainer_rows",
    "build_market_gainer_rows", "build_market_trading_value_rows",
    "calculate_volume_profile", "describe_screen_freshness",
    "filter_52w_distance", "overlay_realtime_quotes", "select_chart_window",
)
