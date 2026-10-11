from __future__ import annotations
import ast
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
required = [
    "src/krx_research/qt/widgets/security_search_panel.py",
    "src/krx_research/qt/services/security_search_service.py",
    "src/krx_research/qt/presentation/screen_presenter.py",
    "src/krx_research/qt/presentation/column_catalog.py",
    "src/krx_research/qt/controllers/chart_controller.py",
    "src/krx_research/qt/services/error_log_service.py",
]
for rel in required:
    if not (ROOT / rel).exists(): errors.append(f"missing: {rel}")

screen_query = (ROOT / "src/krx_research/qt/models/screen_query.py").read_text(encoding="utf-8")
if "comparison_ticker" not in screen_query or "이동평균 유사배열" not in screen_query:
    errors.append("EMA similarity comparison ticker is not enforced")

presenter = (ROOT / "src/krx_research/qt/presentation/screen_presenter.py").read_text(encoding="utf-8")
catalog = (ROOT / "src/krx_research/qt/presentation/column_catalog.py").read_text(encoding="utf-8")
for text in ("데이터베이스", "기준일"):
    if text not in presenter:
        errors.append(f"Korean presentation missing: {text}")
if "배열 유사도(%)" not in catalog:
    errors.append("Korean presentation missing: 배열 유사도(%)")

# Pure view files must not reach PostgreSQL/repositories directly.
for folder in (ROOT / "src/krx_research/qt/windows", ROOT / "src/krx_research/qt/widgets"):
    for path in folder.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom): module = node.module or ""
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("krx_research.database", "krx_research.data_engine")) or ".repository" in alias.name:
                        errors.append(f"view reaches repository: {path.relative_to(ROOT)} -> {alias.name}")
                continue
            if module.startswith(("krx_research.database", "krx_research.data_engine")) or ".repository" in module:
                errors.append(f"view reaches repository: {path.relative_to(ROOT)} -> {module}")

# No raw SQL statements in layered Qt view/controller files.
for folder in (ROOT / "src/krx_research/qt/windows", ROOT / "src/krx_research/qt/widgets", ROOT / "src/krx_research/qt/controllers"):
    for path in folder.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        if re.search(r'(?is)\bselect\b.+?\bfrom\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b|\bdelete\s+from\b', text):
            errors.append(f"raw SQL exposed in UI/controller layer: {path.relative_to(ROOT)}")

print("V5_FEATURE_CHECK:", "PASS" if not errors else "FAIL")
for error in errors: print(" -", error)
sys.exit(1 if errors else 0)
