from __future__ import annotations

from krx_research_nextgen.infrastructure.task_logging import TaskLog
from krx_research_nextgen.models.chart_data import ChartBundle, IndicatorConfig, TIMEFRAME_LOAD_FACTORS
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.services.chart_service import ChartService


class MarketChartService:
    def __init__(
        self,
        repository: PostgreSQLChartRepository,
        chart_service: ChartService | None = None,
    ) -> None:
        self._repository = repository
        self._chart_service = chart_service or ChartService()

    def prepare_recent_chart(
        self,
        symbol: str | None = None,
        *,
        limit: int = 550,
        config: IndicatorConfig | None = None,
        timeframe: str = "D",
    ) -> ChartBundle:
        normalized = str(symbol or self._repository.sample_latest_symbol()).strip().zfill(6)
        selected = timeframe.strip().upper()
        if selected not in TIMEFRAME_LOAD_FACTORS:
            raise ValueError(f"Unsupported chart timeframe: {timeframe}")
        raw_limit = min(10_000, max(253, int(limit) * TIMEFRAME_LOAD_FACTORS[selected]))

        with TaskLog(
            "chart_load",
            stock_code=normalized,
            limit=limit,
            relation=self._repository.ohlcv_relation,
        ) as task:
            frame = self._repository.load_recent_ohlcv(
                normalized, limit=raw_limit
            )
            task.info(f"ohlcv_rows={len(frame)}")
            if not frame.empty:
                task.info(f"first_date={frame.index.min()}")
                task.info(f"last_date={frame.index.max()}")

            name = self._repository.stock_name(normalized)
            title = f"{name} ({normalized})" if name else normalized
            flow = self._repository.load_investor_flow(normalized, frame.index.min(), frame.index.max())
            bundle = self._chart_service.prepare(
                title, frame, config=config, timeframe=timeframe, investor_flow=flow, display_limit=limit,
            )

            task.info(f"chart_title={bundle.symbol}")
            task.info("indicators=RSI,MACD,Bollinger")
            return bundle

    def diagnostics(self) -> dict[str, object]:
        return self._repository.diagnostics()
