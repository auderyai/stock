from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "src/krx_research/application/xing_db/e2e_models.py",
    ROOT / "src/krx_research/application/xing_db/e2e_ports.py",
    ROOT / "src/krx_research/application/xing_db/e2e_service.py",
    ROOT / "src/krx_research/infrastructure/xing_db/e2e_probe_repository.py",
    ROOT / "src/krx_research/infrastructure/xing_db/e2e_command_runner.py",
    ROOT / "scripts/verify_v41_db_menu_e2e.py",
]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def main() -> int:
    missing = [str(p) for p in FILES if not p.is_file()]
    if missing:
        print("FAIL: missing files:", *missing, sep="\n")
        return 1
    app_files = [p for p in FILES if "/application/" in p.as_posix()]
    forbidden = ("psycopg", "PySide6", "PyQt5", "PyQt6", "ctypes", "subprocess")
    errors: list[str] = []
    for path in app_files:
        bad = sorted(n for n in imports(path) if n.startswith(forbidden))
        if bad:
            errors.append(f"application boundary violation {path.name}: {bad}")
    text = (ROOT / "src/krx_research/application/xing_db/e2e_service.py").read_text(encoding="utf-8")
    required = [
        "before != 0", "after != 1", "after2 != 1",
        "raw_after != 4", "cp_after != 1", "raw_after2 != 4", "cp_after2 != 1",
        "kospi200 != 200", "kosdaq150 != 150", "snap.duplicates",
    ]
    for token in required:
        if token not in text:
            errors.append(f"missing verification invariant: {token}")
    runner = (ROOT / "src/krx_research/infrastructure/xing_db/e2e_command_runner.py").read_text(encoding="utf-8")
    for entry in ("run_daily_pipeline.py", "update_ls_investor_date_range.py", "update_xing_venue_history.py"):
        if entry not in runner:
            errors.append(f"menu entry not verified: {entry}")
    if errors:
        for e in errors:
            print("FAIL:", e)
        return 1
    print("V41_E2E_STATIC_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
