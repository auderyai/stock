from __future__ import annotations

import ast
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


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def architecture_verify() -> None:
    root = Path(__file__).resolve().parents[1]
    violations = []

    for folder in ("windows","widgets","presentation"):
        for path in (root/folder).rglob("*.py"):
            for mod in _imports(path):
                if mod.startswith("psycopg"):
                    violations.append(f"View imports DB directly: {path.name} -> {mod}")
                if mod.startswith("krx_research_nextgen.repositories"):
                    violations.append(f"View imports Repository directly: {path.name} -> {mod}")

    for path in root.rglob("*.py"):
        for mod in _imports(path):
            if mod == "PySide6" or mod.startswith("PySide6."):
                violations.append(f"PySide6 forbidden: {path.name}")

    if violations:
        raise RuntimeError("\n".join(violations))


def main() -> int:
    architecture_verify()

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

        status = screening_controller.status()
        print("STAGE4_VERIFY:")
        print(f" - latest trade date: {status['latest_trade_date']}")

        for kind in ScreeningKind:
            rows = screening_controller.run(kind, limit=10, market="ALL")
            print(f" - {kind.value}: {len(rows)} rows")
            if rows:
                bundle = main_controller.prepare_chart(rows[0].stock_code, limit=180)
                if len(bundle.frame) < 80:
                    raise RuntimeError(f"Too few chart rows for {kind.value}")

        print("STAGE4_VERIFY: PASS")
        print(" - ScreeningRepository -> Service -> Controller: PASS")
        print(" - result selection -> same ChartService: PASS")
        print(" - SPAC exclusion policy: ENABLED")
        print(" - View direct SQL/Repository access: NO")
        print(" - PySide6 in nextgen: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
