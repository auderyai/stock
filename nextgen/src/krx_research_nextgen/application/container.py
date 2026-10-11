from __future__ import annotations

from krx_research_nextgen.controllers.main_window_controller import MainWindowController
from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.controllers.auxiliary_controller import AuxiliaryController
from krx_research_nextgen.repositories.auxiliary_repository import AuxiliaryRepository
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.repositories.security_repository import SecurityRepository
from krx_research_nextgen.services.market_chart_service import MarketChartService
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.security_search_service import SecuritySearchService
from krx_research_nextgen.services.auxiliary_service import AuxiliaryService
from krx_research_nextgen.services.scenario_service import ScenarioService
from krx_research_nextgen.windows.stage4_main_window import Stage4MainWindow
from pathlib import Path
from krx_research.database.settings import resolve_database_target
from krx_research.qt.services.assistant_service import AssistantService


class ApplicationContainer:
    """Composition root owning repositories and the PyQt6 main window."""

    def __init__(self) -> None:
        self.chart_repository = PostgreSQLChartRepository()
        self.security_repository = SecurityRepository()
        self.screening_repository = ScreeningRepository()
        self.main_controller = MainWindowController(
            SecuritySearchService(self.security_repository),
            MarketChartService(self.chart_repository),
            ScenarioService(),
        )
        self.auxiliary_controller = AuxiliaryController(AuxiliaryService(AuxiliaryRepository()))
        self.assistant_service = AssistantService(resolve_database_target(Path(r"C:\stock"), read_only=True))
        self.window = Stage4MainWindow(
            self.main_controller,
            ScreeningController(ScreeningService(self.screening_repository)),
            self.auxiliary_controller,
            self.assistant_service,
        )
        self.auxiliary_controller.stock_requested.connect(self.window.open_stock_chart)

    def close(self) -> None:
        self.screening_repository.close()
        self.security_repository.close()
        self.chart_repository.close()

    def __enter__(self) -> "ApplicationContainer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
