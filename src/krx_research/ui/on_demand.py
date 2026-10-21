"""Narrow compatibility API for the former mixed on-demand UI module."""

from krx_research.analytics.on_demand_screening import (
    build_overlay_snapshot,
    calculate_screen,
)
from krx_research.collectors.naver_investor import fetch_naver_investor_trend
from krx_research.data_engine.on_demand_repository import (
    CHART_CACHE_MAX_TICKERS,
    CHART_CACHE_SECONDS,
    SCREEN_CACHE_SECONDS,
    PostgreSQLOnDemandData,
)
from krx_research.models.on_demand import OnDemandChartResult, OnDemandScreenResult
from krx_research.policies.workstation_options import TIMEFRAME_LABELS

__all__ = (
    "OnDemandChartResult", "OnDemandScreenResult", "PostgreSQLOnDemandData",
    "CHART_CACHE_MAX_TICKERS", "CHART_CACHE_SECONDS", "SCREEN_CACHE_SECONDS",
    "TIMEFRAME_LABELS", "build_overlay_snapshot", "calculate_screen",
    "fetch_naver_investor_trend",
)
