"""Market-data collectors.

Heavy modules are loaded lazily so the 32-bit xingAPI worker can import the
COM-only subpackage without importing pandas or GUI/analysis dependencies.
"""
from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "FULL_COVERAGE_STATUS": (".history_coverage", "FULL_COVERAGE_STATUS"),
    "QUALITY_LIMITED_STATUS": (".history_coverage", "QUALITY_LIMITED_STATUS"),
    "SOURCE_LIMITED_STATUS": (".history_coverage", "SOURCE_LIMITED_STATUS"),
    "OhlcvCoverageError": (".history_coverage", "OhlcvCoverageError"),
    "assess_ohlcv_coverage": (".history_coverage", "assess_ohlcv_coverage"),
    "coverage_establishes_requested_end": (".history_coverage", "coverage_establishes_requested_end"),
    "effective_history_start": (".history_coverage", "effective_history_start"),
    "require_ohlcv_coverage": (".history_coverage", "require_ohlcv_coverage"),
    "INDEX_GAINER_DEFINITIONS": (".index_membership", "INDEX_GAINER_DEFINITIONS"),
    "INDEX_GAINER_SCREEN_TYPES": (".index_membership", "INDEX_GAINER_SCREEN_TYPES"),
    "IndexDefinition": (".index_membership", "IndexDefinition"),
    "IndexMembership": (".index_membership", "IndexMembership"),
    "fetch_index_membership": (".index_membership", "fetch_index_membership"),
    "MarketDataError": (".market_data", "MarketDataError"),
    "OhlcvComparison": (".market_data", "OhlcvComparison"),
    "compare_ohlcv_sources": (".market_data", "compare_ohlcv_sources"),
    "fetch_fdr_naver_ohlcv": (".market_data", "fetch_fdr_naver_ohlcv"),
    "fetch_ohlcv": (".market_data", "fetch_ohlcv"),
    "fetch_ohlcv_for_recovery": (".market_data", "fetch_ohlcv_for_recovery"),
    "fetch_pykrx_naver_ohlcv": (".market_data", "fetch_pykrx_naver_ohlcv"),
    "fetch_security_master": (".market_data", "fetch_security_master"),
    "normalize_security_master": (".market_data", "normalize_security_master"),
    "normalize_ticker": (".market_data", "normalize_ticker"),
    "normalize_ohlcv": (".ohlcv_quality", "normalize_ohlcv"),
    "KRX_HTTPS_CURRENT_SOURCE": (".realtime_quotes", "KRX_HTTPS_CURRENT_SOURCE"),
    "NAVER_COMBINED_SOURCE": (".realtime_quotes", "NAVER_COMBINED_SOURCE"),
    "NAVER_CURRENT_SOURCE": (".realtime_quotes", "NAVER_CURRENT_SOURCE"),
    "NAVER_KRX_SOURCE": (".realtime_quotes", "NAVER_KRX_SOURCE"),
    "NAVER_NXT_SOURCE": (".realtime_quotes", "NAVER_NXT_SOURCE"),
    "PYKRX_CURRENT_SOURCE": (".realtime_quotes", "PYKRX_CURRENT_SOURCE"),
    "QUOTE_VENUE_COMBINED": (".realtime_quotes", "QUOTE_VENUE_COMBINED"),
    "QUOTE_VENUE_KRX": (".realtime_quotes", "QUOTE_VENUE_KRX"),
    "QUOTE_VENUE_NXT": (".realtime_quotes", "QUOTE_VENUE_NXT"),
    "QUOTE_VENUES": (".realtime_quotes", "QUOTE_VENUES"),
    "RealtimeQuoteSnapshot": (".realtime_quotes", "RealtimeQuoteSnapshot"),
    "fetch_realtime_krx_quotes": (".realtime_quotes", "fetch_realtime_krx_quotes"),
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
