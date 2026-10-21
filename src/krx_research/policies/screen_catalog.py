"""Single source of truth for legacy workstation screen families."""

from krx_research.collectors.index_membership import INDEX_GAINER_SCREEN_TYPES
from krx_research.policies.workstation_options import SCREEN_TITLES

INVESTOR_FLOW_SCREEN_DEFINITIONS = {
    f"{market.lower()}_{investor}_net_{direction}": (market, investor, direction)
    for market in ("KOSPI", "KOSDAQ")
    for investor in ("foreign", "institution", "individual")
    for direction in ("buy", "sell")
}
MARKET_GAINER_DEFINITIONS = {
    "kospi_daily_gainers": "KOSPI", "kosdaq_daily_gainers": "KOSDAQ",
    "kospi_kosdaq_daily_gainers": "KOSPI+KOSDAQ",
}
MARKET_GAINER_SCREEN_TYPES = frozenset(MARKET_GAINER_DEFINITIONS)
MARKET_WEEKLY_GAINER_DEFINITIONS = {
    "weekly_return": "KOSPI+KOSDAQ", "kospi_weekly_gainers": "KOSPI",
    "kosdaq_weekly_gainers": "KOSDAQ",
}
MARKET_WEEKLY_GAINER_SCREEN_TYPES = frozenset(MARKET_WEEKLY_GAINER_DEFINITIONS)
MARKET_TRADING_VALUE_DEFINITIONS = {"kospi_kosdaq_daily_trading_value": "KOSPI+KOSDAQ"}
WEEKLY_TRADING_VALUE_DEFINITIONS = {
    "kospi_weekly_trading_value": "KOSPI", "kosdaq_weekly_trading_value": "KOSDAQ",
    "kospi_kosdaq_weekly_trading_value": "KOSPI+KOSDAQ",
}
WEEKLY_TRADING_VALUE_SCREEN_TYPES = frozenset(WEEKLY_TRADING_VALUE_DEFINITIONS)
MARKET_TRADING_VALUE_SCREEN_TYPES = frozenset(MARKET_TRADING_VALUE_DEFINITIONS)
MARKET_RESULT_DEFINITIONS = {
    **MARKET_GAINER_DEFINITIONS, **MARKET_WEEKLY_GAINER_DEFINITIONS,
    **MARKET_TRADING_VALUE_DEFINITIONS, **WEEKLY_TRADING_VALUE_DEFINITIONS,
}
MARKET_RESULT_SCREEN_TYPES = frozenset(MARKET_RESULT_DEFINITIONS)
INDEX_DAILY_MEMBERSHIP_TYPES = {
    "kospi200_kosdaq150_daily_gainers": (
        "kospi200_daily_gainers", "kosdaq150_daily_gainers",
    ),
}
INDEX_WEEKLY_MEMBERSHIP_TYPES = {
    "kospi200_weekly_gainers": ("kospi200_daily_gainers",),
    "kosdaq150_weekly_gainers": ("kosdaq150_daily_gainers",),
    "kospi200_kosdaq150_weekly_gainers": (
        "kospi200_daily_gainers", "kosdaq150_daily_gainers",
    ),
}
INDEX_WEEKLY_SCREEN_TYPES = frozenset(INDEX_WEEKLY_MEMBERSHIP_TYPES)
INDEX_MEMBERSHIP_TYPES = {**INDEX_DAILY_MEMBERSHIP_TYPES, **INDEX_WEEKLY_MEMBERSHIP_TYPES}
INDEX_RELATED_SCREEN_TYPES = frozenset(set(INDEX_GAINER_SCREEN_TYPES) | set(INDEX_MEMBERSHIP_TYPES))
WEEKLY_SCREEN_TYPES = frozenset({
    "bollinger_breakout", *MARKET_WEEKLY_GAINER_SCREEN_TYPES,
    *INDEX_WEEKLY_SCREEN_TYPES, *WEEKLY_TRADING_VALUE_SCREEN_TYPES,
})
DIRECT_ON_DEMAND_SCREEN_TYPES = frozenset(SCREEN_TITLES)
INVESTOR_FLOW_SCREEN_TYPES = frozenset(INVESTOR_FLOW_SCREEN_DEFINITIONS)
DAILY_GAINER_SCREEN_TYPES = frozenset(
    set(INDEX_GAINER_SCREEN_TYPES) | set(INDEX_DAILY_MEMBERSHIP_TYPES)
    | set(MARKET_GAINER_SCREEN_TYPES) | set(MARKET_TRADING_VALUE_SCREEN_TYPES)
)
