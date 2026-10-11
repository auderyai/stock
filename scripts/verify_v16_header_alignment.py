from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
QT = ROOT / "src" / "krx_research" / "qt"
policy_path = QT / "presentation" / "table_policy.py"
common_path = QT / "common.py"
result_table_path = QT / "widgets" / "result_table.py"

policy = policy_path.read_text(encoding="utf-8")
common = common_path.read_text(encoding="utf-8")
result_table = result_table_path.read_text(encoding="utf-8")
errors: list[str] = []

checks = {
    "single global header policy": "def header_alignment" in policy,
    "all headers centered": "return int(Qt.AlignCenter)" in policy,
    "model delegates header alignment": "self._policy.header_alignment" in common,
    "all standard result grids share DataFrameModel": "DataFrameModel" in result_table,
    "columns remain user-resizable": "QHeaderView.Interactive" in result_table,
    "columns remain user-movable": "setSectionsMovable(True)" in result_table,
}
for name, ok in checks.items():
    if not ok:
        errors.append(name)

# Reject ad-hoc horizontal header alignment overrides outside the shared policy/model.
for path in QT.rglob("*.py"):
    if path in {policy_path, common_path}:
        continue
    text = path.read_text(encoding="utf-8")
    if "setDefaultAlignment(" in text or "setTextAlignment(" in text:
        errors.append(f"ad-hoc header/cell alignment override: {path.relative_to(ROOT)}")

print("V16_GLOBAL_HEADER_ALIGNMENT_CHECK:", "PASS" if not errors else "FAIL")
for error in errors:
    print(" -", error)
sys.exit(1 if errors else 0)
