from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("USERPROFILE", "")) / "new_stock"
cmd = ROOT / "tools" / "setup" / "TEST_V41_8_DB_MENU_E2E.cmd"
ps1 = ROOT / "tools" / "setup" / "RUN_V41_8_DB_MENU_E2E.ps1"

failures: list[str] = []
for path in (cmd, ps1):
    if not path.is_file():
        failures.append(f"missing: {path}")

if cmd.is_file():
    text = cmd.read_text(encoding="utf-8", errors="strict")
    if " -File " not in text:
        failures.append("TEST cmd must invoke PowerShell with -File")
    if "2^>^&1" in text or "Tee-Object" in text:
        failures.append("TEST cmd must not embed PowerShell pipeline/redirect syntax")

if ps1.is_file():
    text = ps1.read_text(encoding="utf-8", errors="strict")
    required = [
        "$env:PYTHONUTF8 = '1'",
        "$env:PYTHONIOENCODING = 'utf-8'",
        "2>&1 | Tee-Object",
        "$rc = $LASTEXITCODE",
        "exit $rc",
    ]
    for token in required:
        if token not in text:
            failures.append(f"runner missing token: {token}")

if failures:
    print("V41_8_WRAPPER_CHECK: FAIL")
    for item in failures:
        print(f"FAIL: {item}")
    raise SystemExit(1)

print("V41_8_WRAPPER_CHECK: PASS")
