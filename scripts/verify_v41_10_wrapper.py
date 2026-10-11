from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(os.environ.get("USERPROFILE", "")) / "new_stock"
cmd = ROOT / "tools" / "setup" / "TEST_V41_10_DB_MENU_E2E.cmd"
runner = ROOT / "scripts" / "run_v41_10_e2e_with_log.py"

failures: list[str] = []
for path in (cmd, runner):
    if not path.is_file():
        failures.append(f"missing: {path}")

if cmd.is_file():
    text = cmd.read_text(encoding="utf-8", errors="strict")
    lowered = text.lower()
    executable_lines = [
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("rem ", "::", "echo "))
    ]
    if any("powershell" in line or ".ps1" in line or "tee-object" in line for line in executable_lines):
        failures.append("TEST cmd executes a prohibited shell/script path")
    if "run_v41_10_e2e_with_log.py" not in lowered:
        failures.append("TEST cmd must invoke Python log runner")

if runner.is_file():
    source = runner.read_text(encoding="utf-8", errors="strict")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        failures.append(f"runner syntax error: {exc}")
        tree = None

    required = [
        'env["PYTHONUTF8"] = "1"',
        'env["PYTHONIOENCODING"] = "utf-8"',
        "stderr=subprocess.STDOUT",
        'log.open("w", encoding="utf-8"',
    ]
    for token in required:
        if token not in source:
            failures.append(f"runner missing token: {token}")

    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr.lower()
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id.lower()
            if func_name not in {"popen", "run", "call", "check_call", "check_output"}:
                continue
            literals: list[str] = []
            for arg in node.args:
                for child in ast.walk(arg):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        literals.append(child.value.lower())
            if any("powershell" in value or value.endswith(".ps1") for value in literals):
                failures.append("Python runner actually invokes a prohibited shell/script")
                break

if failures:
    print("V41_10_WRAPPER_CHECK: FAIL")
    for item in failures:
        print(f"FAIL: {item}")
    raise SystemExit(1)

print("V41_10_WRAPPER_CHECK: PASS")
