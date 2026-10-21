from __future__ import annotations

import ast
from pathlib import Path

from krx_research_nextgen.controllers.main_window_controller import MainWindowController
from krx_research_nextgen.repositories.postgresql_chart_repository import PostgreSQLChartRepository
from krx_research_nextgen.repositories.security_repository import SecurityRepository
from krx_research_nextgen.services.market_chart_service import MarketChartService
from krx_research_nextgen.services.security_search_service import SecuritySearchService
from krx_research_nextgen.services.scenario_service import ScenarioService


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def architecture_verify() -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []

    for folder in ("windows", "presentation"):
        for path in (root / folder).rglob("*.py"):
            for mod in _imports(path):
                if mod.startswith("psycopg"):
                    violations.append(f"View imports DB directly: {path.name} -> {mod}")
                if mod.startswith("krx_research_nextgen.repositories"):
                    violations.append(f"View imports Repository directly: {path.name} -> {mod}")

    for path in root.rglob("*.py"):
        for mod in _imports(path):
            if mod == "PySide6" or mod.startswith("PySide6."):
                violations.append(f"PySide6 forbidden in nextgen: {path.name}")

    if violations:
        raise RuntimeError("\n".join(violations))


def main() -> int:
    architecture_verify()

    with PostgreSQLChartRepository() as chart_repo, SecurityRepository() as security_repo:
        controller = MainWindowController(
            SecuritySearchService(security_repo),
            MarketChartService(chart_repo),
            ScenarioService(),
        )

        rows = controller.search_securities("", limit=20)
        if not rows:
            raise RuntimeError("Security search returned zero rows.")

        selected = rows[0]
        bundle = controller.prepare_chart(selected.stock_code, limit=180)
        if len(bundle.frame) < 80:
            raise RuntimeError("Chart returned too few rows.")

        status = controller.status()

        print("STAGE3_VERIFY: PASS")
        print(f" - security relation: {status.get('security_relation')}")
        print(f" - OHLCV relation: {status.get('ohlcv_relation')}")
        print(f" - search rows: {len(rows)}")
        print(f" - selected: {selected.stock_name} ({selected.stock_code})")
        print(f" - chart rows: {len(bundle.frame)}")
        print(" - View -> Controller -> Service -> Repository: PASS")
        print(" - View direct SQL/Repository access: NO")
        print(" - PySide6 in nextgen: NO")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
