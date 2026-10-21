"""Compatibility facade for the indicator-scenario domain engine.

The implementation lives in :mod:`krx_research.analytics.indicator_scenario` so
Qt views/controllers never depend on legacy UI modules for business logic.
"""
from krx_research.analytics.indicator_scenario import (
    FEATURES,
    INDICATORS,
    MARKET_FEATURES,
    Checkpoint,
    PathResult,
    add_market_features,
    evaluate,
    features_from_ohlcv,
    scenario_path,
)

__all__ = (
    "FEATURES", "INDICATORS", "MARKET_FEATURES", "Checkpoint", "PathResult",
    "add_market_features", "evaluate", "features_from_ohlcv", "scenario_path",
)
