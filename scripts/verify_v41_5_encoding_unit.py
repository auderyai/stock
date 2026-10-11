from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from krx_research.infrastructure.xing_db.e2e_command_runner import LocalMenuCommandRunner


class Cp949Stream:
    encoding = "cp949"


def main() -> int:
    source = "정상 한글 + replacement=\ufffd + emoji=🚀"
    safe = LocalMenuCommandRunner._console_safe(source, Cp949Stream())
    safe.encode("cp949")  # must never raise
    if "정상 한글" not in safe:
        raise AssertionError("representable Korean text was unexpectedly lost")
    if "\ufffd" in safe:
        raise AssertionError("U+FFFD must be replaced at cp949 console boundary")
    print("V41_5_ENCODING_UNIT_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
