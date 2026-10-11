from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# V40/V39 active runtime scope only. Historical verification/migration scripts are
# intentionally excluded: they are not imported by menu 2/5/7 and must not turn a
# current-runtime architecture check into a repository archaeology check.
RUNTIME_TARGETS = (
    SRC / "krx_research" / "application" / "xing_db",
    SRC / "krx_research" / "infrastructure" / "xing_db",
    ROOT / "scripts" / "run_daily_pipeline.py",
    ROOT / "scripts" / "run_xing_db_menu.py",
    ROOT / "scripts" / "run_fast_daily_update.py",
    ROOT / "scripts" / "update_ls_investor_raw.py",
    ROOT / "scripts" / "update_ls_investor_date_range.py",
    ROOT / "scripts" / "update_xing_venue_history.py",
    ROOT / "scripts" / "run_daily_integrated.py",
    ROOT / "scripts" / "test_v39_xing_runtime_gui.py",
)


def iter_python_files():
    seen: set[Path] = set()
    for target in RUNTIME_TARGETS:
        if target.is_file():
            paths = (target,)
        elif target.is_dir():
            paths = target.rglob("*.py")
        else:
            continue
        for path in paths:
            path = path.resolve()
            if path not in seen:
                seen.add(path)
                yield path


def imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or "")
    return out


def main() -> int:
    errors: list[str] = []
    runtime_files = list(iter_python_files())
    if not runtime_files:
        errors.append("V40 런타임 검증 대상 Python 파일이 없습니다.")

    # Import-based check prevents false positives from comments, docs, strings,
    # and old migration/verifier files that are not part of the active runtime.
    for path in runtime_files:
        rel = path.relative_to(ROOT)
        try:
            modules = imports(path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"Python parse 실패 {rel}: {exc}")
            continue
        mixed = sorted({m for m in modules if m.startswith(("PyQt5", "PyQt6"))})
        if mixed:
            errors.append(f"Qt binding 혼용 {rel}: {mixed}")

    # Application layer must depend on ports/domain abstractions, not DB/Qt/DLL infra.
    app = SRC / "krx_research" / "application" / "xing_db"
    for path in app.glob("*.py"):
        modules = imports(path)
        bad = sorted({
            m for m in modules
            if m.startswith("psycopg")
            or m.startswith("PySide6")
            or "xingdll" in m
            or m.startswith("krx_research.infrastructure")
        })
        if bad:
            errors.append(f"Application 계층 인프라 직접 import {path.name}: {bad}")

    repo = SRC / "krx_research" / "infrastructure" / "xing_db" / "postgresql_repository.py"
    if not repo.is_file():
        errors.append("PostgreSQL repository adapter 누락")

    required_entries = (
        "run_daily_pipeline.py",
        "run_xing_db_menu.py",
        "run_fast_daily_update.py",
        "update_ls_investor_raw.py",
        "update_ls_investor_date_range.py",
        "update_xing_venue_history.py",
        "run_daily_integrated.py",
    )
    for required in required_entries:
        if not (ROOT / "scripts" / required).is_file():
            errors.append(f"메뉴 entry 누락: {required}")

    # If the V39 qualification GUI is present, it must still be PySide6 based.
    v39_gui = ROOT / "scripts" / "test_v39_xing_runtime_gui.py"
    if v39_gui.is_file():
        modules = imports(v39_gui)
        if not any(m.startswith("PySide6") for m in modules):
            errors.append("V39 runtime GUI가 PySide6를 import하지 않습니다.")

    if errors:
        print("V40_1_ARCHITECTURE_CHECK: FAIL")
        for item in errors:
            print("FAIL:", item)
        return 1

    print("V40_1_ARCHITECTURE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
