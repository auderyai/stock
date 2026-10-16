"""Local KRX workstation UI APIs, loaded only when requested."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "ChartDisplayOptions": (".chart_options", "ChartDisplayOptions"),
    "LABEL_TO_TIMEFRAME": (".chart_options", "LABEL_TO_TIMEFRAME"),
    **{name: (".charts", name) for name in (
        "DEFAULT_PROFILE_BINS", "MAX_PROFILE_BINS", "MIN_PROFILE_BINS", "build_chart_figure",
    )},
    **{name: (".classic_strategies", name) for name in (
        "ALEXANDER_ELDER", "ALL_STRATEGIES", "ELLIOTT_WAVE", "JESSE_LIVERMORE",
        "STRATEGY_OPTIONS", "ClassicStrategyAssessment", "assess_classic_strategies",
        "format_strategy_assessments",
    )},
    **{name: (".data", name) for name in (
        "DAILY_GAINER_SCREEN_TYPES", "DATA_SOURCE_MODES", "DATABASE_SOURCE_MODE",
        "INDEX_RELATED_SCREEN_TYPES", "INDEX_WEEKLY_SCREEN_TYPES", "MARKET_GAINER_DEFINITIONS",
        "MARKET_GAINER_SCREEN_TYPES", "MARKET_RESULT_SCREEN_TYPES", "MARKET_TRADING_VALUE_SCREEN_TYPES",
        "REALTIME_SOURCE_MODE", "SCREEN_TITLES", "WEEKLY_SCREEN_TYPES", "ChartDataset",
        "ScreenDataset", "WorkstationData", "build_index_gainer_rows", "build_index_weekly_gainer_rows",
        "build_market_gainer_rows", "build_market_trading_value_rows", "calculate_volume_profile",
        "describe_screen_freshness", "overlay_realtime_quotes", "select_chart_window",
    )},
    **{name: (".rise_reason", name) for name in (
        "GoogleNewsItem", "RiseReasonLookupError", "RiseReasonReport", "build_google_news_query",
        "build_google_news_urls", "fetch_google_rise_reason", "format_rise_reason_report",
        "parse_google_news_rss",
    )},
    "TIMEFRAME_LABELS": (".on_demand", "TIMEFRAME_LABELS"),
}

__all__ = tuple(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted((*globals(), *__all__))
