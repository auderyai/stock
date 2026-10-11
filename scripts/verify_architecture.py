from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
errors: list[str] = []

PROHIBITED_IMPORTS = ("tkinter", "sqlite3", "pymysql", "mysql", "mariadb", "PyQt5", "PyQt6")
# Current V6 baseline still uses PySide6. PyQt6+Finplot conversion is a later controlled phase.

def imports_of(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError as e:
        errors.append(f"Syntax error: {path.relative_to(ROOT)}: {e}")
        return []
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods

for p in list(SRC.rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
    if p.name.startswith("verify_"):
        continue
    for mod in imports_of(p):
        if mod == "tkinter" or mod.startswith("tkinter."):
            errors.append(f"Tkinter prohibited: {p.relative_to(ROOT)}")
        if mod == "sqlite3" or mod.startswith("sqlite3."):
            errors.append(f"SQLite prohibited: {p.relative_to(ROOT)}")
        if any(mod == x or mod.startswith(x + ".") for x in ("pymysql","mysql","mariadb")):
            errors.append(f"MariaDB/MySQL prohibited: {p.relative_to(ROOT)}")
        if any(mod == x or mod.startswith(x + ".") for x in ("PyQt5","PyQt6")):
            errors.append(f"Qt mixing prohibited in V6 baseline; use PySide6 only: {p.relative_to(ROOT)}")

required = [
    "src/krx_research/qt/application/app.py",
    "src/krx_research/qt/controllers/workstation_controller.py",
    "src/krx_research/qt/services/screening_service.py",
    "src/krx_research/qt/services/chart_service.py",
    "src/krx_research/qt/services/export_service.py",
    "src/krx_research/qt/workers/task_runner.py",
    "src/krx_research/qt/models/screen_query.py",
    "src/krx_research/qt/widgets/query_panel.py",
    "src/krx_research/qt/widgets/result_table.py",
    "src/krx_research/qt/windows/workstation_window.py",
    "src/krx_research/qt/controllers/chart_controller.py",
    "src/krx_research/qt/services/security_search_service.py",
    "src/krx_research/qt/widgets/security_search_panel.py",
    "src/krx_research/qt/presentation/screen_presenter.py",
    "src/krx_research/qt/controllers/featured_controller.py",
    "src/krx_research/qt/services/featured_service.py",
    "src/krx_research/qt/controllers/theme_controller.py",
    "src/krx_research/qt/services/theme_service.py",
    "src/krx_research/qt/strategies/chart_navigation.py",
    "src/krx_research/qt/presentation/table_policy.py",
    "src/krx_research/qt/controllers/investor_dashboard_controller.py",
    "src/krx_research/qt/services/investor_dashboard_service.py",
    "src/krx_research/qt/windows/investor_dashboard_window.py",
    "src/krx_research/qt/controllers/market_index_controller.py",
    "src/krx_research/qt/services/market_index_service.py",
    "src/krx_research/qt/repositories/market_index_repository.py",
    "src/krx_research/qt/windows/market_index_window.py",
    "src/krx_research/qt/models/date_range.py",
    "src/krx_research/qt/presentation/investor_presenter.py",
    "src/krx_research/qt/application/window_factory.py",
    "src/krx_research/qt/windows/scenario_window.py",
    "src/krx_research/qt/controllers/scenario_controller.py",
    "src/krx_research/qt/services/scenario_service.py",
    "src/krx_research/qt/models/scenario.py",
    "src/krx_research/qt/presentation/scenario_presenter.py",
    "src/krx_research/qt/presentation/scenario_plotter.py",
    "src/krx_research/database/scenario_market.py",
    "src/krx_research/analytics/indicator_scenario.py",
]
for rel in required:
    if not (ROOT / rel).exists():
        errors.append(f"Missing OOP layer: {rel}")

# Views/widgets must not import DB directly.
view_files = list((SRC/"krx_research"/"qt"/"windows").glob("*.py")) + list((SRC/"krx_research"/"qt"/"widgets").glob("*.py"))
for p in view_files:
    for mod in imports_of(p):
        if mod.startswith(("krx_research.database", "krx_research.data_engine.postgresql")):
            errors.append(f"View imports DB directly: {p.relative_to(ROOT)}")

controller_path = SRC/"krx_research"/"qt"/"controllers"/"workstation_controller.py"
if controller_path.exists():
    controller_text = controller_path.read_text(encoding="utf-8", errors="ignore")
    for forbidden in (
        "krx_research.ui.investor_dashboard",
        "krx_research.ui.market_index_window",
        "krx_research.featured_research.gui",
        "krx_research.theme_research.gui",
    ):
        if forbidden in controller_text:
            errors.append(f"Legacy GUI dependency in WorkstationController: {forbidden}")

print("ARCHITECTURE_CHECK:", "PASS" if not errors else "FAIL")
for e in errors:
    print(" -", e)
sys.exit(1 if errors else 0)
