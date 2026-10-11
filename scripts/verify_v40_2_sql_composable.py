from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "src" / "krx_research" / "infrastructure" / "xing_db" / "postgresql_repository.py"


def main() -> int:
    if not REPO.is_file():
        print("V40_2_SQL_COMPOSABLE_CHECK: FAIL")
        print("FAIL: repository file missing")
        return 1

    text = REPO.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(REPO))
    errors: list[str] = []

    # Prevent the exact production failure seen on V40.1: BaseDataRepository
    # exposes _core_schema as a psycopg Composable/Identifier. Wrapping it in
    # sql.Identifier() again raises TypeError at runtime.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_identifier = (
            isinstance(fn, ast.Attribute)
            and fn.attr == "Identifier"
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "sql"
        )
        if not is_identifier:
            continue
        for arg in node.args:
            if (
                isinstance(arg, ast.Attribute)
                and arg.attr in {"_core_schema", "_ohlcv_table"}
            ):
                errors.append(
                    f"Composable double-wrap: sql.Identifier(...{arg.attr}) at line {node.lineno}"
                )

    expected = 'sql.SQL("{}.venue_ohlcv_daily").format(self._repo._core_schema)'
    if expected not in text:
        errors.append("latest_venue_date() must format _core_schema directly")

    if errors:
        print("V40_2_SQL_COMPOSABLE_CHECK: FAIL")
        for e in errors:
            print("FAIL:", e)
        return 1

    print("V40_2_SQL_COMPOSABLE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
