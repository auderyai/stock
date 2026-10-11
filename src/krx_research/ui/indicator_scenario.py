"""Compatibility facade for the indicator-scenario domain engine.

The implementation lives in :mod:`krx_research.analytics.indicator_scenario` so
Qt views/controllers never depend on legacy UI modules for business logic.
"""
from krx_research.analytics.indicator_scenario import *  # noqa: F401,F403
