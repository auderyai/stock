from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
create = ROOT / "tools" / "git" / "CREATE_V42_BASELINE.cmd"
verify = ROOT / "tools" / "git" / "VERIFY_V42_BASELINE.cmd"
errors: list[str] = []
for p in (create, verify):
    if not p.is_file():
        errors.append(f"missing: {p}")

if create.is_file():
    text = create.read_text(encoding="utf-8")
    required = [
        "git add src scripts tools KRX_Menu_Launcher config",
        "git diff --cached --check --",
        "src/krx_research/application/job_menu",
        "src/krx_research/infrastructure/job_menu",
        "src/krx_research/qt/job_menu",
        "v42-db-menu-integration-complete",
        "Refusing to move it automatically",
    ]
    for token in required:
        if token not in text:
            errors.append(f"CREATE missing token: {token}")
    if "git diff --cached --check ||" in text:
        errors.append("CREATE still performs whole-tree whitespace check")

if verify.is_file():
    text = verify.read_text(encoding="utf-8")
    for token in ("git rev-list -n 1", "git rev-parse HEAD", "does not point at current HEAD"):
        if token not in text:
            errors.append(f"VERIFY missing token: {token}")

if errors:
    print("V42_2_GIT_PATCH_CHECK: FAIL")
    for e in errors:
        print("FAIL:", e)
    raise SystemExit(1)
print("V42_2_GIT_PATCH_CHECK: PASS")
