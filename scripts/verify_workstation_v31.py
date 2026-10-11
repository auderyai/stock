"""Exercise the v31 screen and selectable chart against the configured DB."""

from __future__ import annotations

import json
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg

from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.database import PostgreSQLSettings, resolve_database_target
from krx_research.ui import ChartDisplayOptions, WorkstationData, build_chart_figure


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    target = resolve_database_target(project_root, read_only=True)
    if not isinstance(target, PostgreSQLSettings):
        raise RuntimeError("workstation v31은 PostgreSQL 설정이 필요합니다.")
    data = WorkstationData(target)
    screen = data.load_screen("high_52w")
    if data._on_demand is None:  # noqa: SLF001 - explicit integration check.
        raise RuntimeError("PostgreSQL 온디맨드 엔진이 활성화되지 않았습니다.")
    with BaseDataRepository(data._on_demand.settings) as repository:  # noqa: SLF001
        sample_ticker = repository.sample_ohlcv_ticker()
    if sample_ticker is None:
        raise RuntimeError("차트를 검증할 일봉 종목이 없습니다.")
    chart = data.load_chart(sample_ticker)
    chart_checks: dict[str, int] = {}
    for timeframe in ("D", "W", "M", "Q", "Y"):
        frame = chart.bars(timeframe)
        if frame.empty:
            raise RuntimeError(f"{sample_ticker} {timeframe}봉 계산 결과가 없습니다.")
        required = {
            "open",
            "high",
            "low",
            "close",
            "volume",
            "rsi_14",
            "macd_oscillator",
            "stoch_slow_k",
            "stoch_slow_d",
        }
        if missing := required.difference(frame.columns):
            raise RuntimeError(f"{timeframe}봉 지표 누락: {sorted(missing)}")
        figure = build_chart_figure(
            chart,
            trading_days=50,
            profile_bins=15,
            options=ChartDisplayOptions(
                timeframe=timeframe,
                show_volume=True,
                show_rsi=True,
                show_macd=True,
                show_stochastic=True,
                show_institution=True,
                show_foreign=True,
                show_individual=True,
            ),
        )
        FigureCanvasAgg(figure).draw()
        chart_checks[timeframe] = len(frame)
        figure.clear()
    print(
        json.dumps(
            {
                "status": "ok",
                "screen_source": screen.run["source"],
                "screen_date": screen.run["as_of_date"],
                "high_52w_rows": len(screen.rows),
                "sample_ticker": sample_ticker,
                "chart_rows": chart_checks,
                "investor_timeframes": sorted(chart.investor),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
