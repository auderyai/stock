from __future__ import annotations
import sys
from PyQt6.QtWidgets import QApplication
from krx_research_nextgen.controllers.main_window_controller import MainWindowController
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.repositories.security_repository import SecurityRepository
from krx_research_nextgen.services.market_chart_service import MarketChartService
from krx_research_nextgen.services.security_search_service import SecuritySearchService
from krx_research_nextgen.services.scenario_service import ScenarioService
from krx_research_nextgen.windows.stage3_main_window import Stage3MainWindow

def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    chart_repo = PostgreSQLChartRepository()
    security_repo = SecurityRepository()
    controller = MainWindowController(
        SecuritySearchService(security_repo),
        MarketChartService(chart_repo),
        ScenarioService(),
    )
    window = Stage3MainWindow(controller)
    window.show()
    try:
        return app.exec()
    finally:
        security_repo.close()
        chart_repo.close()

if __name__ == "__main__":
    raise SystemExit(main())
