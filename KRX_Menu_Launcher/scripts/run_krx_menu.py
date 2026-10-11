from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
for candidate in (HERE.parents[2], HERE.parents[1], HERE.parent):
    if (candidate / "src" / "krx_research").is_dir() and (candidate / ".venv" / "Scripts" / "python.exe").is_file():
        ROOT = candidate
        break
else:
    raise SystemExit("C:\\stock 프로젝트 루트를 찾을 수 없습니다.")

SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from krx_research.qt.job_menu.window import main

if __name__ == "__main__":
    raise SystemExit(main())
