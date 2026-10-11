"""Static checks for package import boundaries that must stay acyclic."""
from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "krx_research"
errors: list[str] = []


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names

# Package initializers must stay lightweight.  They are executed before a
# requested submodule and are the most common source of circular imports.
qt_init = SRC / "qt" / "__init__.py"
ui_init = SRC / "ui" / "__init__.py"
for module in imported_modules(qt_init):
    if module.startswith("krx_research"):
        errors.append(f"qt/__init__.py must not eagerly import {module}")
for module in imported_modules(ui_init):
    if module.startswith("krx_research.qt") or module.endswith("workstation"):
        errors.append(f"ui/__init__.py creates GUI back-reference: {module}")

# Layering rules: Views/widgets must not depend on compatibility workstation
# modules.  Controllers may use services/windows, but the legacy compatibility
# module is never a dependency of a layered Qt module.
for path in (SRC / "qt").rglob("*.py"):
    if path.name == "__init__.py":
        continue
    for module in imported_modules(path):
        if module in {"krx_research.ui.workstation", "krx_research.qt.workstation"}:
            # qt/workstation.py is the entry compatibility facade and is allowed
            # to depend inward, but nothing below the layered tree should import it.
            if path.name != "workstation.py":
                errors.append(f"layer imports compatibility facade: {path.relative_to(ROOT)} -> {module}")

# Specific regression guard for the V3 startup failure:
# qt.chart_window -> qt.windows.chart_window -> ui package initializer ->
# ui.workstation -> qt.chart_window.
ui_init_text = ui_init.read_text(encoding="utf-8")
if ".workstation import" in ui_init_text or "krx_research.qt" in ui_init_text:
    errors.append("V3 circular-import regression detected in ui/__init__.py")

print("IMPORT_BOUNDARY_CHECK:", "PASS" if not errors else "FAIL")
for error in errors:
    print(" -", error)
sys.exit(1 if errors else 0)
