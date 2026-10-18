from __future__ import annotations

import os
import subprocess
import sys

from validate_stock_drive_repair import ROOT, _changed_files, validate_scope


def main() -> int:
    paths = _changed_files()
    validate_scope(
        paths,
        allowed_files={"requirements-cloud-worker.txt", "scripts/opendart_financial_backfill.py"},
        allowed_prefixes=("src/krx_research/financial_backfill/", "tests/financial_backfill/"),
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for command in (
        (sys.executable, "-m", "unittest", "discover", "-s", "tests/financial_backfill", "-p", "test_*.py"),
        (sys.executable, "-m", "compileall", "-q", "scripts/opendart_financial_backfill.py", "src/krx_research/financial_backfill"),
    ):
        subprocess.run(command, cwd=ROOT, env=env, check=True)
    print(f"[PASS] 제한된 OpenDART 자동 수정 검증: {len(paths)}개 파일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
