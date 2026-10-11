from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=[
 ROOT/"src/krx_research/application/xing_db/service.py",
 ROOT/"src/krx_research/application/xing_db/e2e_models.py",
 ROOT/"src/krx_research/application/xing_db/e2e_ports.py",
 ROOT/"src/krx_research/application/xing_db/e2e_service.py",
 ROOT/"src/krx_research/infrastructure/xing_db/e2e_probe_repository.py",
 ROOT/"src/krx_research/infrastructure/xing_db/e2e_command_runner.py",
 ROOT/"scripts/run_xing_db_menu.py",
 ROOT/"scripts/update_ls_investor_date_range.py",
 ROOT/"scripts/verify_v41_db_menu_e2e.py",
]
def imports(path:Path)->set[str]:
    tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out=set()
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): out.update(a.name for a in n.names)
        elif isinstance(n,ast.ImportFrom) and n.module: out.add(n.module)
    return out
def main()->int:
    errors=[]
    for p in FILES:
        if not p.is_file(): errors.append(f"missing {p}")
    app=[p for p in FILES if "/application/" in p.as_posix()]
    forbidden=("psycopg","PySide6","PyQt5","PyQt6","ctypes","subprocess")
    for p in app:
        bad=sorted(n for n in imports(p) if n.startswith(forbidden))
        if bad: errors.append(f"application boundary violation {p.name}: {bad}")
    svc=(ROOT/"src/krx_research/application/xing_db/service.py").read_text(encoding="utf-8")
    for token in (
        "_INDEX_COUNT_TOLERANCE = 5",
        "request_first = min(first, last - dt.timedelta(days=28))",
        "force_refresh: bool = False",
        "expected if force_refresh else",
    ):
        if token not in svc: errors.append(f"missing production invariant: {token}")
    e2e=(ROOT/"src/krx_research/application/xing_db/e2e_service.py").read_text(encoding="utf-8")
    for token in (
        "find_existing_combined",
        "find_completed_investor",
        "affected_rows <= 0",
        "abs(snap.kospi200 - 200) > 5",
    ):
        if token not in e2e: errors.append(f"missing E2E invariant: {token}")
    runner=(ROOT/"src/krx_research/infrastructure/xing_db/e2e_command_runner.py").read_text(encoding="utf-8")
    for token in ("run_xing_db_menu.py","update_ls_investor_date_range.py","--force-refresh","--no-investor","V41_AFFECTED_ROWS"):
        if token not in runner: errors.append(f"missing runner token: {token}")
    if "sql.Identifier(self._repo._core_schema)" in "\n".join(p.read_text(encoding="utf-8") for p in FILES if p.suffix==".py"):
        errors.append("SQL composable double-wrap regression")
    if errors:
        for e in errors: print("FAIL:",e)
        return 1
    print("V41_1_STATIC_CHECK: PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
