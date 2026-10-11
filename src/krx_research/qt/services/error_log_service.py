from __future__ import annotations

from datetime import datetime
from pathlib import Path


class ErrorLogService:
    """Keep one latest technical error log inside the new_stock project."""

    def __init__(self, root: str | Path | None = None, filename: str = "stock_error.log") -> None:
        project_root = Path(__file__).resolve().parents[4]
        self.root = Path(root) if root is not None else project_root / "logs"
        self.path = self.root / filename

    def write(self, trace_text: str) -> Path | None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                f"[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{trace_text.rstrip()}\n",
                encoding="utf-8",
            )
            return self.path
        except Exception:
            return None
