from __future__ import annotations

import os
import re
import threading
import traceback
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\stock")
TASK_LOG_ROOT = ROOT / "logs" / "tasks"


def _safe_name(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", str(value)).strip("_")
    return text[:80] or "task"


class TaskLog(AbstractContextManager["TaskLog"]):
    """One physical UTF-8 log file per task execution."""

    def __init__(self, task_name: str, **metadata: Any) -> None:
        self.task_name = _safe_name(task_name)
        self.metadata = metadata
        now = datetime.now()
        day_dir = TASK_LOG_ROOT / now.strftime("%Y%m%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        stamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        pid = os.getpid()
        tid = threading.get_ident()
        self.path = day_dir / f"{stamp}_{self.task_name}_p{pid}_t{tid}.log"
        self._fh = None
        self._started = now

    def __enter__(self) -> "TaskLog":
        self._fh = self.path.open("w", encoding="utf-8", newline="\n")
        self.info("=" * 72)
        self.info(f"TASK START: {self.task_name}")
        self.info(f"started_at={self._started.isoformat(timespec='milliseconds')}")
        self.info(f"pid={os.getpid()} thread={threading.get_ident()}")
        for key, value in self.metadata.items():
            self.info(f"{key}={value}")
        self.info("=" * 72)
        return self

    def info(self, message: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S.%f}] {message}"
        if self._fh is None:
            self._fh = self.path.open("a", encoding="utf-8", newline="\n")
        self._fh.write(line + "\n")
        self._fh.flush()

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc is None:
                self.info("STATUS=SUCCESS")
            else:
                self.info(f"STATUS=ERROR type={exc_type.__name__ if exc_type else type(exc).__name__}")
                self.info(f"ERROR={exc}")
                formatted = "".join(traceback.format_exception(exc_type, exc, tb))
                for line in formatted.rstrip().splitlines():
                    self.info("TRACE " + line)
            elapsed = (datetime.now() - self._started).total_seconds()
            self.info(f"elapsed_seconds={elapsed:.3f}")
            self.info("=" * 72)
            self.info(f"TASK END: {self.task_name}")
        finally:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
        return False
