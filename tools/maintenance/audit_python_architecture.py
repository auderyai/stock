"""Static architecture audit for the C:\\stock Python sources."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKIP = {".git", "_rollback", ".venv_finplot", ".venv_krx_menu", "POSTGRESQL_BACKUP"}
VIEW_PARTS = {"ui", "windows", "widgets", "presentation"}
DB_IMPORTS = ("psycopg", "sqlalchemy", "sqlite", "pymysql", "mariadb")


def python_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if not SKIP.intersection(p.relative_to(ROOT).parts)]


def span(node: ast.AST) -> int:
    return getattr(node, "end_lineno", node.lineno) - node.lineno + 1


def module_name(path: Path) -> str | None:
    for base in (ROOT / "src", ROOT / "nextgen" / "src"):
        try:
            rel = path.relative_to(base).with_suffix("")
        except ValueError:
            continue
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)
    return None


def main() -> None:
    files = python_files()
    modules = {name: path for path in files if (name := module_name(path))}
    imported: Counter[str] = Counter()
    long_functions: list[tuple[int, str, int, str]] = []
    long_classes: list[tuple[int, str, int, str]] = []
    view_db: list[tuple[str, int, str]] = []
    layer_violations: list[tuple[str, int, str]] = []
    syntax_errors: list[tuple[str, str]] = []

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            syntax_errors.append((rel, str(exc)))
            continue
        parts = set(path.relative_to(ROOT).parts)
        is_view = bool(parts & VIEW_PARTS) or path.name.endswith(("_gui.py", "_window.py"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and span(node) >= 50:
                long_functions.append((span(node), rel, node.lineno, node.name))
            elif isinstance(node, ast.ClassDef) and span(node) >= 200:
                long_classes.append((span(node), rel, node.lineno, node.name))
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
                if is_view:
                    for alias in node.names:
                        if alias.name.lower().startswith(DB_IMPORTS):
                            view_db.append((rel, node.lineno, f"import {alias.name}"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported[node.module] += 1
                if is_view and node.module.lower().startswith(DB_IMPORTS):
                    view_db.append((rel, node.lineno, f"from {node.module}"))
                current_layer = next((x for x in ("windows", "controllers", "services", "repositories") if x in parts), None)
                target_layer = next((x for x in ("windows", "controllers", "services", "repositories") if f".{x}." in f".{node.module}."), None)
                forbidden = {"windows": {"services", "repositories"}, "controllers": {"repositories"}}
                if target_layer in forbidden.get(current_layer, set()):
                    layer_violations.append((rel, node.lineno, node.module))
            if is_view and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr.lower() in {"execute", "executemany", "cursor"}:
                    call = ast.get_source_segment(text, node) or node.func.attr
                    view_db.append((rel, node.lineno, call.splitlines()[0][:120]))

    unused = []
    for name, path in modules.items():
        if path.name == "__init__.py":
            continue
        hits = sum(count for imported_name, count in imported.items() if imported_name == name or imported_name.startswith(name + "."))
        if not hits:
            unused.append(path.relative_to(ROOT).as_posix())

    sections = {
        "SYNTAX_ERRORS": syntax_errors,
        "LONG_FUNCTIONS_GE_50": sorted(long_functions, reverse=True),
        "LONG_CLASSES_GE_200": sorted(long_classes, reverse=True),
        "VIEW_DB_CALLS": sorted(set(view_db)),
        "LAYER_IMPORT_VIOLATIONS": sorted(set(layer_violations)),
        "UNIMPORTED_MODULE_CANDIDATES": sorted(unused),
    }
    print(f"FILES={len(files)} MODULES={len(modules)}")
    for title, rows in sections.items():
        print(f"\n[{title}] {len(rows)}")
        for row in rows:
            print(" | ".join(map(str, row)) if isinstance(row, tuple) else row)


if __name__ == "__main__":
    main()
