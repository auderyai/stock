from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
FILES = {
    "service": ROOT / "src/krx_research/application/xing_db/service.py",
    "rate": ROOT / "src/krx_research/infrastructure/xing_db/rate_limited_bridge.py",
    "runner": ROOT / "scripts/run_xing_db_menu.py",
    "menu5": ROOT / "scripts/update_ls_investor_date_range.py",
}
errors: list[str] = []
for label, path in FILES.items():
    if not path.is_file():
        errors.append(f"missing {label}: {path}")

if not errors:
    service = FILES["service"].read_text(encoding="utf-8")
    rate = FILES["rate"].read_text(encoding="utf-8")
    runner = FILES["runner"].read_text(encoding="utf-8")
    menu5 = FILES["menu5"].read_text(encoding="utf-8")

    for token in ("request_failures", "code_request_failures", "force-refresh 중 t1702 요청 실패"):
        if token not in service:
            errors.append(f"service guard missing: {token}")
    if "time.sleep" in service or "import time" in service:
        errors.append("application service must not implement transport sleeps")
    for token in ("RateLimitedRawTrBridge", "_TR_INTERVALS", "t1516", "t1702", "_RETRY_DELAYS", "ETK_Request"):
        if token not in rate:
            errors.append(f"rate-limit bridge missing: {token}")
    if "RateLimitedRawTrBridge" not in runner:
        errors.append("run_xing_db_menu.py does not use rate-limit bridge")
    if "RateLimitedRawTrBridge" not in menu5:
        errors.append("update_ls_investor_date_range.py does not use rate-limit bridge")

    # Current runtime scripts must stay PySide6/Python-only: no PyQt import.
    for label in ("runner", "menu5"):
        tree = ast.parse(FILES[label].read_text(encoding="utf-8"), filename=str(FILES[label]))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.startswith(("PyQt5", "PyQt6")) for n in names):
                errors.append(f"Qt binding violation: {label}")

if errors:
    print("V41_3_STATIC_CHECK: FAIL")
    for e in errors:
        print("FAIL:", e)
    raise SystemExit(1)
print("V41_3_STATIC_CHECK: PASS")
