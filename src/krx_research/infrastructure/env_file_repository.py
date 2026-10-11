from __future__ import annotations

import os
from pathlib import Path


class EnvFileRepository:
    """Preserve unrelated .env entries and atomically update selected keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    def save(self, values: dict[str, str]) -> None:
        lines = self.path.read_text(encoding="utf-8-sig").splitlines() if self.path.is_file() else []
        pending, output = dict(values), []
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            output.append(f"{key}={pending.pop(key)}" if key in pending else line)
        if output and output[-1]: output.append("")
        output.extend(f"{key}={value}" for key, value in pending.items())
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
