from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from krx_research_nextgen.models.chart_data import IndicatorConfig
from krx_research_nextgen.presentation.finplot_adapter import FinplotChartAdapter
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.services.market_chart_service import MarketChartService


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    symbol = args[0].strip().zfill(6) if args else None
    limit = int(args[1]) if len(args) > 1 else 550

    app = QApplication.instance() or QApplication(sys.argv)

    with PostgreSQLChartRepository() as repo:
        service = MarketChartService(repo)
        bundle = service.prepare_recent_chart(
            symbol,
            limit=limit,
            config=IndicatorConfig(rsi_period=14.9),
        )

    FinplotChartAdapter().render(bundle)
    _ = app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
