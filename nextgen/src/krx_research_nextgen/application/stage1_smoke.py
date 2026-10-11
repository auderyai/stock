from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from krx_research_nextgen.application.smoke_data import build_sample_ohlcv
from krx_research_nextgen.models.chart_data import IndicatorConfig
from krx_research_nextgen.presentation.finplot_adapter import FinplotChartAdapter
from krx_research_nextgen.services.chart_service import ChartService


def main() -> int:
    # The PyQt6 application is intentionally created in this isolated nextgen process.
    app = QApplication.instance() or QApplication(sys.argv)

    frame = build_sample_ohlcv()
    service = ChartService()
    bundle = service.prepare(
        "STAGE1-FINPLOT-SMOKE",
        frame,
        config=IndicatorConfig(rsi_period=14.9),
    )
    FinplotChartAdapter().render(bundle)

    # finplot.show() runs the event loop in normal use; return keeps this entrypoint testable.
    _ = app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
