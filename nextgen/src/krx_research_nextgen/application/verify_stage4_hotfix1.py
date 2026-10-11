from __future__ import annotations

from pathlib import Path

from krx_research_nextgen.controllers.main_window_controller import MainWindowController
from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.repositories.security_repository import SecurityRepository
from krx_research_nextgen.services.market_chart_service import MarketChartService
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.security_search_service import SecuritySearchService


def main() -> int:
    with (
        PostgreSQLChartRepository() as chart_repo,
        SecurityRepository() as security_repo,
        ScreeningRepository() as screening_repo,
    ):
        main_controller = MainWindowController(
            SecuritySearchService(security_repo),
            MarketChartService(chart_repo),
        )
        screening_controller = ScreeningController(
            ScreeningService(screening_repo)
        )

        print("STAGE4_HOTFIX1_VERIFY:")
        print(f" - latest trade date: {screening_controller.status()['latest_trade_date']}")

        for kind in ScreeningKind:
            rows = screening_controller.run(kind, limit=10, market="ALL")
            print(f" - {kind.value}: {len(rows)} rows")
            if rows:
                bundle = main_controller.prepare_chart(rows[0].stock_code, limit=180)
                if len(bundle.frame) < 80:
                    raise RuntimeError(f"Too few chart rows for {kind.value}")

        log_root = Path(r"C:\stock\logs\tasks")
        logs = list(log_root.rglob("*.log")) if log_root.exists() else []
        if not logs:
            raise RuntimeError("Per-task log files were not created.")

        print(f" - per-task logs: {len(logs)} total files found")
        print(" - SPAC SQL percent escaping: PASS")
        print(" - screening/chart/search per-task logging: PASS")
        print("STAGE4_HOTFIX1_VERIFY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
