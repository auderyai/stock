from krx_research.policies.chart_analysis import DEFAULT_CHART_ANALYSIS_POLICY as policy

expected = {
    "rsi": ("close", (14, 9), "EMA"),
    "macd": ("close", (12, 26, 9), "EMA"),
    "stochastic": ("close", (5, 3, 3), "EMA"),
    "moving_average": ("EMA", (5, 10, 15, 33, 56, 112, 224, 448)),
    "bollinger": ("close", 20, 2.0, "EMA"),
    "volume": "Stock PostgreSQL",
    "market": (("KOSPI", "1001"), ("KOSDAQ", "2001"), (3, 20, 60, 252),
               (20, 60), 252, 252, 1000, "Stock PostgreSQL"),
}
actual = {
    "rsi": (policy.rsi.source, policy.rsi.periods, policy.rsi.smoothing),
    "macd": (policy.macd_oscillator.source, policy.macd_oscillator.periods,
             policy.macd_oscillator.smoothing),
    "stochastic": (policy.stochastic_slow.source, policy.stochastic_slow.periods,
                    policy.stochastic_slow.smoothing),
    "moving_average": (policy.moving_average_kind, policy.moving_average_periods),
    "bollinger": (policy.bollinger.source, policy.bollinger.period,
                  policy.bollinger.deviations, policy.bollinger.center),
    "volume": policy.volume_source,
    "market": (*policy.market_context.indices, policy.market_context.return_horizons,
               policy.market_context.volatility_windows,
               policy.market_context.regime_lookback_days,
               policy.market_context.annualization_days,
               policy.market_context.history_limit, policy.market_context.source),
}
if actual != expected:
    raise SystemExit(f"CHART_ANALYSIS_POLICY: FAIL\nexpected={expected}\nactual={actual}")
print("CHART_ANALYSIS_POLICY: PASS")
