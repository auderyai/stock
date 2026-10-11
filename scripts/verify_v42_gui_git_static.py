from __future__ import annotations

import ast
import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "src/krx_research/application/job_menu/models.py",
    ROOT / "src/krx_research/application/job_menu/ports.py",
    ROOT / "src/krx_research/application/job_menu/service.py",
    ROOT / "src/krx_research/infrastructure/job_menu/python_job_executor.py",
    ROOT / "src/krx_research/qt/job_menu/worker.py",
    ROOT / "src/krx_research/qt/job_menu/controller.py",
    ROOT / "src/krx_research/qt/job_menu/window.py",
    ROOT / "scripts/run_krx_menu.py",
    ROOT / "scripts/migrate_v42_legacy_jobs.py",
]


def imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def fail(msg: str) -> None:
    print("V42_GUI_GIT_STATIC: FAIL")
    print("FAIL:", msg)
    raise SystemExit(2)

for path in FILES:
    if not path.is_file():
        fail(f"missing {path.relative_to(ROOT)}")
    py_compile.compile(str(path), doraise=True)

qt_files = [p for p in FILES if "/qt/job_menu/" in p.as_posix()]
for path in qt_files:
    imps = imports(path)
    bad = sorted(x for x in imps if x.startswith(("PyQt5", "PyQt6", "tkinter")))
    if bad:
        fail(f"Qt binding mixed in {path.name}: {bad}")

app_files = [p for p in FILES if "/application/job_menu/" in p.as_posix()]
for path in app_files:
    imps = imports(path)
    bad = sorted(x for x in imps if x.startswith(("PySide6", "PyQt", "psycopg", "subprocess", "ctypes")))
    if bad:
        fail(f"application layer violation {path.name}: {bad}")

infra = ROOT / "src/krx_research/infrastructure/job_menu/python_job_executor.py"
if any(x.startswith(("PySide6", "PyQt")) for x in imports(infra)):
    fail("infrastructure executor must not import Qt")

launcher_text = (ROOT / "scripts/run_krx_menu.py").read_text(encoding="utf-8")
if "tkinter" in launcher_text or "PyQt" in launcher_text:
    fail("canonical launcher is not PySide6-only")

print("V42_GUI_GIT_STATIC: PASS")
