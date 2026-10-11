from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
TARGET = ROOT / "src/krx_research/infrastructure/xing_db/e2e_command_runner.py"


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    ast.parse(text)
    required = [
        'child_env["PYTHONUTF8"] = "1"',
        'child_env["PYTHONIOENCODING"] = "utf-8"',
        'encoding="utf-8"',
        'errors="replace"',
        "_console_safe",
        "_safe_print",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        print("V41_5_ENCODING_STATIC_CHECK: FAIL")
        for token in missing:
            print("missing:", token)
        return 1
    if 'print(clean, flush=True)' in text:
        print("V41_5_ENCODING_STATIC_CHECK: FAIL")
        print("unsafe direct console print remains")
        return 1
    print("V41_5_ENCODING_STATIC_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
