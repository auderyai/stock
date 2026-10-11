from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

LOG = ROOT / "logs" / "runtime" / "run_krx_menu_bootstrap.log"


def launch() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write("\n[BOOT] run_krx_menu import start\n")
    try:
        from krx_research.qt.job_menu.window import main
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write("[BOOT] window module imported\n")
        result = int(main() or 0)
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"[BOOT] event loop exited rc={result}\n")
        return result
    except BaseException:
        with LOG.open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        raise

if __name__ == "__main__":
    raise SystemExit(launch())
