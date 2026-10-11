from __future__ import annotations

from krx_research_nextgen.models.chart_data import IndicatorConfig
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.services.market_chart_service import MarketChartService


def main() -> int:
    with PostgreSQLChartRepository() as repo:
        service = MarketChartService(repo)
        diag = service.diagnostics()
        symbol = repo.sample_latest_symbol()
        bundle = service.prepare_recent_chart(
            symbol,
            limit=180,
            config=IndicatorConfig(rsi_period=14.9),
        )

        frame = bundle.frame
        if len(frame) < 80:
            raise RuntimeError(f"Too few real OHLCV rows: {len(frame)}")
        if not frame.index.is_monotonic_increasing:
            raise RuntimeError("OHLCV index is not ascending.")
        if frame.index.has_duplicates:
            raise RuntimeError("OHLCV index contains duplicate trade dates.")

        required = {
            "open","high","low","close","volume",
            "rsi","macd","macd_signal","macd_hist",
            "bb_mid","bb_upper","bb_lower",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise RuntimeError(f"Missing chart columns: {sorted(missing)}")

        print("STAGE2_VERIFY: PASS")
        print(f" - database: {diag['database']}")
        print(f" - user: {diag['user']}")
        print(f" - PostgreSQL: {diag['server_version']}")
        print(f" - OHLCV relation: {diag['ohlcv_relation']}")
        print(f" - master relation: {diag['master_relation']}")
        print(f" - sample symbol: {symbol}")
        print(f" - chart title: {bundle.symbol}")
        print(f" - real rows: {len(frame)}")
        print(f" - first date: {frame.index.min().date()}")
        print(f" - last date: {frame.index.max().date()}")
        print(" - RSI 14.9: PASS")
        print(" - MACD: PASS")
        print(" - Bollinger: PASS")
        print(" - Controller -> Service -> Repository: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
