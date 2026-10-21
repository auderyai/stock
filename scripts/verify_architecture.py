from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
NEXTGEN = ROOT / "nextgen" / "src"
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


def tree_of(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return None

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
    "src/krx_research/qt/application/job_menu_dependencies.py",
    "src/krx_research/qt/controllers/pattern_search_controller.py",
    "src/krx_research/qt/repositories/pattern_repository.py",
    "src/krx_research/qt/repositories/assistant_repository.py",
    "src/krx_research/policies/chart_analysis.py",
    "src/krx_research/chart_learning/models.py",
    "src/krx_research/chart_learning/service.py",
    "src/krx_research/chart_learning/repository.py",
    "src/krx_research/qt/windows/scenario_window.py",
    "src/krx_research/qt/controllers/scenario_controller.py",
    "src/krx_research/qt/services/scenario_service.py",
    "src/krx_research/qt/models/scenario.py",
    "src/krx_research/qt/presentation/scenario_presenter.py",
    "src/krx_research/qt/presentation/scenario_plotter.py",
    "src/krx_research/database/scenario_market.py",
    "src/krx_research/analytics/indicator_scenario.py",
    "src/krx_research/presentation/table_policy.py",
    "nextgen/src/krx_research_nextgen/widgets/result_table.py",
]
for rel in required:
    if not (ROOT / rel).exists():
        errors.append(f"Missing OOP layer: {rel}")

# Views/widgets must not import DB or repositories directly. Search recursively so
# feature subpackages cannot bypass the same invariant.
view_roots = (
    SRC/"krx_research"/"qt"/"windows",
    SRC/"krx_research"/"qt"/"widgets",
    SRC/"krx_research"/"qt"/"pattern_search",
    SRC/"krx_research"/"qt"/"job_menu",
    NEXTGEN/"krx_research_nextgen"/"windows",
)
view_files = [path for root in view_roots if root.exists() for path in root.rglob("*.py")]
view_files.extend(
    path for path in (
        SRC/"krx_research"/"ui"/"investor_dashboard.py",
        SRC/"krx_research"/"ui"/"charts.py",
        SRC/"krx_research"/"ui"/"workstation.py",
        SRC/"krx_research"/"featured_research"/"gui.py",
        SRC/"krx_research"/"theme_research"/"gui.py",
        SRC/"krx_research"/"qt"/"scenario_window.py",
    ) if path.exists()
)
for p in view_files:
    for mod in imports_of(p):
        if mod.startswith(("krx_research.database", "krx_research.data_engine",
                           "krx_research.qt.repositories", "krx_research_nextgen.repositories")):
            errors.append(f"View imports DB/repository directly: {p.relative_to(ROOT)}")
        if p.name != "controller.py" and (
            mod.startswith("krx_research.qt.services")
            or mod.startswith("krx_research_nextgen.services")
        ):
            errors.append(f"View imports service directly: {p.relative_to(ROOT)}")

# NextGen result grids must use the shared typed ResultTable.  Direct item-table
# construction reintroduces duplicated formatting, lexical numeric sorting and
# inconsistent chart navigation.
nextgen_windows = NEXTGEN / "krx_research_nextgen" / "windows"
for p in nextgen_windows.rglob("*.py"):
    tree = tree_of(p)
    if tree is not None and any(
        isinstance(node, ast.Name) and node.id == "QTableWidget"
        for node in ast.walk(tree)
    ):
        errors.append(f"NextGen window bypasses common ResultTable: {p.relative_to(ROOT)}")

# Services may depend on repository interfaces/objects, but may not open a DB
# connection themselves. SQL execution belongs to repositories/infrastructure.
all_source_files = list(SRC.rglob("*.py")) + list(NEXTGEN.rglob("*.py"))
service_files = {
    path for path in all_source_files
    if "services" in path.parts or path.name == "service.py" or path.name.endswith("_service.py")
}
for p in service_files:
    for mod in imports_of(p):
        if mod == "psycopg" or mod.startswith((
            "psycopg.", "krx_research.database", "krx_research.data_engine.postgresql",
            "krx_research_nextgen.infrastructure.db_settings",
        )):
            errors.append(f"Service imports DB infrastructure directly: {p.relative_to(ROOT)}")

controller_files = {
    path for path in all_source_files
    if "controllers" in path.parts or path.name.endswith("_controller.py")
}
for p in controller_files:
    for mod in imports_of(p):
        if ".repositories" in mod or mod.startswith((
            "psycopg", "krx_research.database", "krx_research.data_engine.postgresql",
            "krx_research_nextgen.infrastructure.db_settings",
        )):
            errors.append(f"Controller imports repository/DB directly: {p.relative_to(ROOT)}")
    tree = tree_of(p)
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name.endswith(("Service", "Repository")):
                errors.append(
                    f"Controller constructs dependency instead of receiving it: "
                    f"{p.relative_to(ROOT)}:{getattr(node, 'lineno', '?')} -> {name}"
                )

# Domain calculations, collectors, and data access are lower layers.  They must
# remain reusable without importing a Qt/UI layer back into themselves.
lower_layer_roots = (
    SRC / "krx_research" / "analytics",
    SRC / "krx_research" / "collectors",
    SRC / "krx_research" / "data_engine",
    SRC / "krx_research" / "database",
    SRC / "krx_research" / "models",
    SRC / "krx_research" / "policies",
)
for p in (path for root in lower_layer_roots for path in root.rglob("*.py")):
    for mod in imports_of(p):
        if mod.startswith(("krx_research.qt", "krx_research.ui")):
            errors.append(f"Lower layer imports UI: {p.relative_to(ROOT)}")

domain_roots = (
    SRC / "krx_research" / "analytics",
    SRC / "krx_research" / "models",
    SRC / "krx_research" / "policies",
)
for p in (path for root in domain_roots for path in root.rglob("*.py")):
    for mod in imports_of(p):
        if mod.startswith(("krx_research.data_engine", "krx_research.database")):
            errors.append(f"Domain layer imports data access: {p.relative_to(ROOT)}")

# Command scripts are orchestration/composition roots. They may call repository
# methods, but SQL execution and connection ownership must remain in repository
# modules so the same safety and transaction rules apply to every entry point.
for p in (ROOT / "scripts").rglob("*.py"):
    if p.name.startswith("verify_"):
        continue
    modules = imports_of(p)
    for mod in modules:
        if mod == "psycopg" or mod.startswith("psycopg."):
            errors.append(f"Script imports psycopg directly: {p.relative_to(ROOT)}")
        if mod == "krx_research.data_engine.postgresql":
            errors.append(f"Script imports BaseDataRepository directly: {p.relative_to(ROOT)}")
    tree = tree_of(p)
    if tree is not None and any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany"}
        for node in ast.walk(tree)
    ):
        errors.append(f"Script executes SQL directly: {p.relative_to(ROOT)}")

# Every general-purpose PostgreSQL boundary is read-only unless a writer opts
# in explicitly.  Keep connection creation centralized so UI repositories
# cannot silently bypass the database safety default.
repository_source = (SRC / "krx_research" / "data_engine" / "postgresql.py").read_text(
    encoding="utf-8", errors="ignore"
)
factory_source = (SRC / "krx_research" / "database" / "factory.py").read_text(
    encoding="utf-8", errors="ignore"
)
nextgen_connection_source = (
    NEXTGEN / "krx_research_nextgen" / "infrastructure" / "postgresql.py"
).read_text(encoding="utf-8", errors="ignore")
for label, source in (
    ("BaseDataRepository", repository_source),
    ("open_research_store", factory_source),
    ("NextGen PostgreSQL", nextgen_connection_source),
    (
        "cloud sync connection",
        (SRC / "krx_research" / "cloud_sync" / "repository.py").read_text(
            encoding="utf-8", errors="ignore"
        ),
    ),
    (
        "featured research repository",
        (SRC / "krx_research" / "featured_research" / "repository.py").read_text(
            encoding="utf-8", errors="ignore"
        ),
    ),
    (
        "theme research repository",
        (SRC / "krx_research" / "theme_research" / "repository.py").read_text(
            encoding="utf-8", errors="ignore"
        ),
    ),
):
    if "read_only: bool = True" not in source and "read_only:bool=True" not in source:
        errors.append(f"PostgreSQL read-only default missing: {label}")
if "SET default_transaction_read_only TO on" not in repository_source:
    errors.append("BaseDataRepository does not enforce PostgreSQL read-only sessions")
if "SET default_transaction_read_only TO on" not in nextgen_connection_source:
    errors.append("NextGen PostgreSQL connector does not enforce read-only sessions")
for p in NEXTGEN.rglob("*.py"):
    if p == NEXTGEN / "krx_research_nextgen" / "infrastructure" / "postgresql.py":
        continue
    if "psycopg.connect(" in p.read_text(encoding="utf-8", errors="ignore"):
        errors.append(f"NextGen repository bypasses common DB connector: {p.relative_to(ROOT)}")

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
